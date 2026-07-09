use anyhow::{bail, Context, Result};
use bytes::Bytes;
use futures_util::Stream;
use reqwest::{header::{HeaderMap, HeaderName, HeaderValue, AUTHORIZATION, CONTENT_TYPE}, Client};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{collections::BTreeMap, pin::Pin, time::Duration};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderRequest {
    pub base_url: String,
    pub model: String,
    #[serde(default)]
    pub api_key: String,
    #[serde(default)]
    pub extra_headers: BTreeMap<String, String>,
    pub messages: Vec<Value>,
    #[serde(default = "default_temperature")]
    pub temperature: f32,
    #[serde(default = "default_top_p")]
    pub top_p: f32,
    #[serde(default = "default_max_tokens")]
    pub max_tokens: u32,
}

fn default_temperature() -> f32 { 1.0 }
fn default_top_p() -> f32 { 0.95 }
fn default_max_tokens() -> u32 { 16384 }

#[derive(Clone)]
pub struct ProviderClient {
    http: Client,
}

impl ProviderClient {
    pub fn new() -> Result<Self> {
        let http = Client::builder()
            .timeout(Duration::from_secs(300))
            .user_agent("APIApp/2.0 Rust")
            .build()?;
        Ok(Self { http })
    }

    pub async fn stream_chat(
        &self,
        request: ProviderRequest,
    ) -> Result<Pin<Box<dyn Stream<Item = Result<Bytes, reqwest::Error>> + Send>>> {
        let base = request.base_url.trim_end_matches('/');
        if !(base.starts_with("https://") || base.starts_with("http://127.0.0.1") || base.starts_with("http://localhost")) {
            bail!("base URL must use HTTPS, except localhost endpoints")
        }

        let mut headers = HeaderMap::new();
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));
        if !request.api_key.trim().is_empty() {
            headers.insert(AUTHORIZATION, HeaderValue::from_str(&format!("Bearer {}", request.api_key.trim()))?);
        }
        for (name, value) in &request.extra_headers {
            let name = HeaderName::from_bytes(name.as_bytes()).context("invalid custom header name")?;
            if name == AUTHORIZATION {
                bail!("Authorization must be supplied through the API key field")
            }
            headers.insert(name, HeaderValue::from_str(value).context("invalid custom header value")?);
        }

        let mut body = serde_json::json!({
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "stream": true
        });
        if base == "https://integrate.api.nvidia.com/v1" {
            body["chat_template_kwargs"] = serde_json::json!({"thinking": false});
        }

        let response = self.http
            .post(format!("{base}/chat/completions"))
            .headers(headers)
            .json(&body)
            .send()
            .await
            .context("failed to contact model provider")?;

        if !response.status().is_success() {
            let status = response.status();
            let detail = response.text().await.unwrap_or_default();
            bail!("provider returned {status}: {detail}")
        }

        Ok(Box::pin(response.bytes_stream()))
    }

    pub async fn test_connection(&self, base_url: &str, api_key: &str) -> Result<Value> {
        let base = base_url.trim_end_matches('/');
        let mut req = self.http.get(format!("{base}/models"));
        if !api_key.trim().is_empty() {
            req = req.bearer_auth(api_key.trim());
        }
        let response = req.send().await?;
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        Ok(serde_json::json!({"ok": status.is_success(), "status": status.as_u16(), "detail": text}))
    }
}
