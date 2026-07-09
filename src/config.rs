use serde::{Deserialize, Serialize};
use std::{env, path::PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AppConfig {
    pub host: String,
    pub port: u16,
    pub provider: ProviderConfig,
    pub workspace_root: Option<PathBuf>,
    pub approval_mode: ApprovalMode,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProviderConfig {
    pub name: String,
    pub base_url: String,
    pub model: String,
    #[serde(skip_serializing)]
    pub api_key: String,
    pub temperature: f32,
    pub top_p: f32,
    pub max_tokens: u32,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ApprovalMode {
    ReadOnly,
    AskBeforeEdits,
    WorkspaceAuto,
    FullAgent,
}

impl Default for ApprovalMode {
    fn default() -> Self {
        Self::AskBeforeEdits
    }
}

impl AppConfig {
    pub fn from_env() -> Self {
        let _ = dotenvy::dotenv();
        let api_key = ["APIAPP_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"]
            .into_iter()
            .find_map(|key| env::var(key).ok().filter(|v| !v.trim().is_empty()))
            .unwrap_or_default();

        let approval_mode = match env::var("APIAPP_APPROVAL_MODE")
            .unwrap_or_else(|_| "ask_before_edits".into())
            .as_str()
        {
            "read_only" => ApprovalMode::ReadOnly,
            "workspace_auto" => ApprovalMode::WorkspaceAuto,
            "full_agent" => ApprovalMode::FullAgent,
            _ => ApprovalMode::AskBeforeEdits,
        };

        Self {
            host: env::var("APIAPP_HOST").unwrap_or_else(|_| "127.0.0.1".into()),
            port: env::var("APIAPP_PORT").ok().and_then(|v| v.parse().ok()).unwrap_or(8765),
            provider: ProviderConfig {
                name: env::var("APIAPP_PROVIDER").unwrap_or_else(|_| "OpenAI-compatible".into()),
                base_url: env::var("APIAPP_BASE_URL")
                    .unwrap_or_else(|_| "https://integrate.api.nvidia.com/v1".into())
                    .trim_end_matches('/')
                    .to_string(),
                model: env::var("APIAPP_MODEL").unwrap_or_else(|_| "deepseek-ai/deepseek-v4-pro".into()),
                api_key,
                temperature: env::var("APIAPP_TEMPERATURE").ok().and_then(|v| v.parse().ok()).unwrap_or(1.0),
                top_p: env::var("APIAPP_TOP_P").ok().and_then(|v| v.parse().ok()).unwrap_or(0.95),
                max_tokens: env::var("APIAPP_MAX_TOKENS").ok().and_then(|v| v.parse().ok()).unwrap_or(16384),
            },
            workspace_root: env::var("APIAPP_WORKSPACE").ok().map(PathBuf::from),
            approval_mode,
        }
    }
}
