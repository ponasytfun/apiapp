use crate::{config::ApprovalMode, guard::PathGuard};
use anyhow::{bail, Context, Result};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{process::Stdio, sync::Arc};
use tokio::{fs, process::Command, time::{timeout, Duration}};
use walkdir::WalkDir;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolRequest {
    pub tool: String,
    #[serde(default)]
    pub args: Value,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ToolResponse {
    pub ok: bool,
    pub tool: String,
    pub result: Value,
}

#[derive(Clone)]
pub struct ToolRuntime {
    guard: Arc<PathGuard>,
    approval_mode: ApprovalMode,
}

impl ToolRuntime {
    pub fn new(guard: Arc<PathGuard>, approval_mode: ApprovalMode) -> Self {
        Self { guard, approval_mode }
    }

    pub async fn execute(&self, request: ToolRequest) -> Result<ToolResponse> {
        let tool = request.tool.clone();
        let result = match request.tool.as_str() {
            "list_directory" => self.list_directory(arg_str(&request.args, "path")?).await?,
            "read_file" => self.read_file(arg_str(&request.args, "path")?).await?,
            "search_text" => self.search_text(arg_str(&request.args, "query")?, request.args.get("path").and_then(Value::as_str).unwrap_or(".")).await?,
            "write_file" => self.write_file(arg_str(&request.args, "path")?, arg_str(&request.args, "content")?).await?,
            "git_status" => self.run_safe_command("git", &["status", "--short"]).await?,
            "git_diff" => self.run_safe_command("git", &["diff", "--"]).await?,
            "run_command" => self.run_command(arg_str(&request.args, "command")?).await?,
            _ => bail!("unknown tool: {}", request.tool),
        };
        Ok(ToolResponse { ok: true, tool, result })
    }

    async fn list_directory(&self, path: &str) -> Result<Value> {
        let root = self.guard.authorize_read(path)?;
        let mut entries = Vec::new();
        let mut rd = fs::read_dir(root).await?;
        while let Some(entry) = rd.next_entry().await? {
            let meta = entry.metadata().await?;
            entries.push(serde_json::json!({
                "name": entry.file_name().to_string_lossy(),
                "directory": meta.is_dir(),
                "size": if meta.is_file() { Some(meta.len()) } else { None }
            }));
        }
        Ok(Value::Array(entries))
    }

    async fn read_file(&self, path: &str) -> Result<Value> {
        let path = self.guard.authorize_read(path)?;
        let meta = fs::metadata(&path).await?;
        if meta.len() > 2_000_000 { bail!("file exceeds 2 MB read limit") }
        let content = fs::read_to_string(&path).await.context("file is not valid UTF-8 text")?;
        Ok(serde_json::json!({"path": path, "content": content}))
    }

    async fn search_text(&self, query: &str, path: &str) -> Result<Value> {
        let root = self.guard.authorize_read(path)?;
        let pattern = Regex::new(&regex::escape(query))?;
        let mut matches = Vec::new();
        for entry in WalkDir::new(root).follow_links(false).into_iter().filter_map(|entry| entry.ok()) {
            if !entry.file_type().is_file() { continue; }
            if entry.metadata().map(|m| m.len() > 1_000_000).unwrap_or(true) { continue; }
            let Ok(content) = std::fs::read_to_string(entry.path()) else { continue; };
            for (index, line) in content.lines().enumerate() {
                if pattern.is_match(line) {
                    matches.push(serde_json::json!({"path": entry.path(), "line": index + 1, "text": line}));
                    if matches.len() >= 200 { return Ok(Value::Array(matches)); }
                }
            }
        }
        Ok(Value::Array(matches))
    }

    async fn write_file(&self, path: &str, content: &str) -> Result<Value> {
        if matches!(self.approval_mode, ApprovalMode::ReadOnly | ApprovalMode::AskBeforeEdits) {
            bail!("write requires approval under current approval mode")
        }
        let path = self.guard.authorize_write(path)?;
        fs::write(&path, content).await?;
        Ok(serde_json::json!({"path": path, "bytesWritten": content.len()}))
    }

    async fn run_safe_command(&self, program: &str, args: &[&str]) -> Result<Value> {
        let output = timeout(Duration::from_secs(60), Command::new(program)
            .args(args)
            .current_dir(self.guard.workspace())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()).await.context("command timed out")??;
        Ok(command_output(output.status.code(), &output.stdout, &output.stderr))
    }

    async fn run_command(&self, command: &str) -> Result<Value> {
        if matches!(self.approval_mode, ApprovalMode::ReadOnly | ApprovalMode::AskBeforeEdits) {
            bail!("terminal command requires approval under current approval mode")
        }
        classify_command(command)?;
        #[cfg(target_os = "windows")]
        let mut cmd = { let mut c = Command::new("cmd"); c.args(["/C", command]); c };
        #[cfg(not(target_os = "windows"))]
        let mut cmd = { let mut c = Command::new("sh"); c.args(["-lc", command]); c };
        let output = timeout(Duration::from_secs(120), cmd
            .current_dir(self.guard.workspace())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()).await.context("command timed out")??;
        Ok(command_output(output.status.code(), &output.stdout, &output.stderr))
    }
}

fn arg_str<'a>(args: &'a Value, name: &str) -> Result<&'a str> {
    args.get(name).and_then(Value::as_str).with_context(|| format!("missing string argument: {name}"))
}

fn command_output(code: Option<i32>, stdout: &[u8], stderr: &[u8]) -> Value {
    serde_json::json!({
        "exitCode": code,
        "stdout": String::from_utf8_lossy(stdout),
        "stderr": String::from_utf8_lossy(stderr)
    })
}

fn classify_command(command: &str) -> Result<()> {
    let lower = command.to_ascii_lowercase();
    let forbidden = ["diskpart", "format ", "shutdown", "rm -rf", "del /s", "rmdir /s", "remove-item -recurse", "git reset --hard", "git clean -fd"];
    if forbidden.iter().any(|needle| lower.contains(needle)) {
        bail!("high-risk command rejected by command policy")
    }
    Ok(())
}
