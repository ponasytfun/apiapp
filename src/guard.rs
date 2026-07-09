use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Component, Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ReferenceRoot {
    pub display_name: String,
    pub path: PathBuf,
}

#[derive(Debug, Clone)]
pub struct PathGuard {
    workspace: PathBuf,
    references: Vec<PathBuf>,
}

impl PathGuard {
    pub fn new(workspace: impl AsRef<Path>, references: &[ReferenceRoot]) -> Result<Self> {
        let workspace = canonicalize_existing(workspace.as_ref())
            .context("workspace path must exist")?;
        let mut protected = Vec::new();
        for reference in references {
            protected.push(canonicalize_existing(&reference.path)
                .with_context(|| format!("reference path does not exist: {}", reference.path.display()))?);
        }
        Ok(Self { workspace, references: protected })
    }

    pub fn workspace(&self) -> &Path { &self.workspace }

    pub fn authorize_read(&self, requested: impl AsRef<Path>) -> Result<PathBuf> {
        let path = self.resolve_existing(requested.as_ref())?;
        if path.starts_with(&self.workspace) || self.references.iter().any(|r| path.starts_with(r)) {
            return Ok(path);
        }
        bail!("path is outside the workspace and registered reference roots")
    }

    pub fn authorize_write(&self, requested: impl AsRef<Path>) -> Result<PathBuf> {
        let path = self.resolve_for_write(requested.as_ref())?;
        if !path.starts_with(&self.workspace) {
            bail!("write rejected: destination escapes writable workspace")
        }
        if self.references.iter().any(|r| path.starts_with(r)) {
            bail!("write rejected: destination is inside a read-only reference root")
        }
        Ok(path)
    }

    fn resolve_existing(&self, requested: &Path) -> Result<PathBuf> {
        let joined = if requested.is_absolute() { requested.to_path_buf() } else { self.workspace.join(requested) };
        reject_parent_components(&joined)?;
        canonicalize_existing(&joined)
    }

    fn resolve_for_write(&self, requested: &Path) -> Result<PathBuf> {
        let joined = if requested.is_absolute() { requested.to_path_buf() } else { self.workspace.join(requested) };
        reject_parent_components(&joined)?;
        if joined.exists() {
            return canonicalize_existing(&joined);
        }
        let parent = joined.parent().context("destination has no parent")?;
        let canonical_parent = canonicalize_existing(parent)?;
        let name = joined.file_name().context("destination has no file name")?;
        Ok(canonical_parent.join(name))
    }
}

fn reject_parent_components(path: &Path) -> Result<()> {
    if path.components().any(|c| matches!(c, Component::ParentDir)) {
        bail!("parent traversal is not allowed")
    }
    Ok(())
}

fn canonicalize_existing(path: &Path) -> Result<PathBuf> {
    std::fs::canonicalize(path).with_context(|| format!("failed to canonicalize {}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn blocks_parent_traversal() {
        let root = std::env::temp_dir().join(format!("apiapp-guard-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let guard = PathGuard::new(&root, &[]).unwrap();
        assert!(guard.authorize_write("../escape.txt").is_err());
        let _ = fs::remove_dir_all(&root);
    }
}
