mod config;
mod guard;
mod provider;
mod tools;

use anyhow::{Context, Result};
use axum::{
    body::Body,
    extract::State,
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use config::AppConfig;
use futures_util::StreamExt;
use guard::{PathGuard, ReferenceRoot};
use provider::{ProviderClient, ProviderRequest};
use serde::Deserialize;
use serde_json::Value;
use std::{net::SocketAddr, path::PathBuf, sync::Arc};
use tokio::sync::RwLock;
use tools::{ToolRequest, ToolRuntime};
use tower_http::{services::ServeDir, trace::TraceLayer};
use tracing::{error, info};

#[derive(Clone)]
struct AppState {
    config: Arc<RwLock<AppConfig>>,
    provider: ProviderClient,
    tools: Arc<RwLock<Option<ToolRuntime>>>,
    references: Arc<RwLock<Vec<ReferenceRoot>>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct WorkspaceRequest {
    path: PathBuf,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ReferenceRequest {
    display_name: String,
    path: PathBuf,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();

    let config = AppConfig::from_env();
    let addr: SocketAddr = format!("{}:{}", config.host, config.port).parse()?;
    let provider = ProviderClient::new()?;
    let references = Arc::new(RwLock::new(Vec::new()));
    let tools = Arc::new(RwLock::new(None));

    let state = AppState {
        config: Arc::new(RwLock::new(config.clone())),
        provider,
        tools: tools.clone(),
        references: references.clone(),
    };

    if let Some(workspace) = config.workspace_root.clone() {
        let guard = PathGuard::new(workspace, &[])?;
        *tools.write().await = Some(ToolRuntime::new(Arc::new(guard), config.approval_mode));
    }

    let app = Router::new()
        .route("/api/health", get(health))
        .route("/api/config", get(get_config))
        .route("/api/chat", post(chat))
        .route("/api/provider/test", post(test_provider))
        .route("/api/workspace", post(set_workspace))
        .route("/api/references", get(list_references).post(add_reference))
        .route("/api/tools/execute", post(execute_tool))
        .nest_service("/", ServeDir::new("." ).append_index_html_on_directories(true))
        .layer(TraceLayer::new_for_http())
        .with_state(state);

    info!("API App 2.0 Rust runtime listening on http://{addr}");
    info!("Open that address in your browser. Ctrl+C stops the runtime.");
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> Json<Value> {
    Json(serde_json::json!({"ok": true, "runtime": "rust", "version": env!("CARGO_PKG_VERSION")}))
}

async fn get_config(State(state): State<AppState>) -> Json<Value> {
    let config = state.config.read().await;
    Json(serde_json::json!({
        "baseUrl": config.provider.base_url,
        "model": config.provider.model,
        "temperature": config.provider.temperature,
        "topP": config.provider.top_p,
        "maxTokens": config.provider.max_tokens,
        "hasServerApiKey": !config.provider.api_key.is_empty(),
        "apiKeySource": if config.provider.api_key.is_empty() { Value::Null } else { Value::String("environment".into()) },
        "approvalMode": config.approval_mode,
        "workspace": config.workspace_root
    }))
}

async fn chat(State(state): State<AppState>, Json(mut request): Json<ProviderRequest>) -> Response {
    let config = state.config.read().await.clone();
    if request.api_key.trim().is_empty() {
        request.api_key = config.provider.api_key;
    }
    if request.base_url.trim().is_empty() { request.base_url = config.provider.base_url; }
    if request.model.trim().is_empty() { request.model = config.provider.model; }

    match state.provider.stream_chat(request).await {
        Ok(stream) => {
            let stream = stream.map(|item| item.map_err(std::io::Error::other));
            let mut response = Response::new(Body::from_stream(stream));
            response.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_static("text/event-stream; charset=utf-8"));
            response.headers_mut().insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache, no-transform"));
            response
        }
        Err(err) => json_error(StatusCode::BAD_GATEWAY, err),
    }
}

async fn test_provider(State(state): State<AppState>, Json(body): Json<Value>) -> Response {
    let base_url = body.get("baseUrl").and_then(Value::as_str).unwrap_or_default();
    let mut api_key = body.get("apiKey").and_then(Value::as_str).unwrap_or_default().to_string();
    if api_key.is_empty() { api_key = state.config.read().await.provider.api_key.clone(); }
    match state.provider.test_connection(base_url, &api_key).await {
        Ok(value) => Json(value).into_response(),
        Err(err) => json_error(StatusCode::BAD_GATEWAY, err),
    }
}

async fn set_workspace(State(state): State<AppState>, Json(body): Json<WorkspaceRequest>) -> Response {
    let refs = state.references.read().await.clone();
    let guard = match PathGuard::new(&body.path, &refs) {
        Ok(guard) => guard,
        Err(err) => return json_error(StatusCode::BAD_REQUEST, err),
    };
    let mut config = state.config.write().await;
    config.workspace_root = Some(guard.workspace().to_path_buf());
    let mode = config.approval_mode;
    *state.tools.write().await = Some(ToolRuntime::new(Arc::new(guard), mode));
    Json(serde_json::json!({"ok": true, "workspace": config.workspace_root})).into_response()
}

async fn list_references(State(state): State<AppState>) -> Json<Value> {
    Json(serde_json::to_value(state.references.read().await.clone()).unwrap_or(Value::Array(vec![])))
}

async fn add_reference(State(state): State<AppState>, Json(body): Json<ReferenceRequest>) -> Response {
    let canonical = match std::fs::canonicalize(&body.path) {
        Ok(path) => path,
        Err(err) => return json_error(StatusCode::BAD_REQUEST, err.into()),
    };
    state.references.write().await.push(ReferenceRoot { display_name: body.display_name, path: canonical });

    let config = state.config.read().await.clone();
    if let Some(workspace) = config.workspace_root {
        let refs = state.references.read().await.clone();
        match PathGuard::new(workspace, &refs) {
            Ok(guard) => *state.tools.write().await = Some(ToolRuntime::new(Arc::new(guard), config.approval_mode)),
            Err(err) => return json_error(StatusCode::BAD_REQUEST, err),
        }
    }
    Json(serde_json::json!({"ok": true})).into_response()
}

async fn execute_tool(State(state): State<AppState>, Json(request): Json<ToolRequest>) -> Response {
    let runtime = state.tools.read().await.clone();
    let Some(runtime) = runtime else {
        return json_error(StatusCode::PRECONDITION_FAILED, anyhow::anyhow!("select a workspace first"));
    };
    match runtime.execute(request).await {
        Ok(result) => Json(serde_json::to_value(result).unwrap_or_default()).into_response(),
        Err(err) => json_error(StatusCode::BAD_REQUEST, err),
    }
}

fn json_error(status: StatusCode, err: anyhow::Error) -> Response {
    error!(error = %err, "request failed");
    (status, Json(serde_json::json!({"error": err.to_string()}))).into_response()
}
