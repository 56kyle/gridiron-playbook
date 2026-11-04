pub mod block;
pub mod document;
pub mod edit;
pub mod error;
pub mod formation;
pub mod quickshare;

use error::{Error, Result};
use std::io::Cursor;
use std::panic::{catch_unwind, AssertUnwindSafe};
use uesave::Save;

pub use document::{inspect_document, new_document, validate_document};
pub use edit::{apply_edit, transfer_plays};
pub use formation::formation_data;

fn save_operation<T>(operation: impl FnOnce() -> Result<T>) -> Result<T> {
    // uesave 0.7.1 panics on some malformed strings. Browser callers isolate traps in a worker.
    catch_unwind(AssertUnwindSafe(operation))
        .map_err(|_| Error::new("invalid_save", "Invalid Unreal save data."))?
}

pub fn sav_to_json(bytes: &[u8]) -> Result<String> {
    if bytes.len() > document::MAX_SAVE_BYTES {
        return Err(Error::new("capacity", "The save exceeds 64 MiB."));
    }
    save_operation(|| {
        let save = Save::read(&mut Cursor::new(bytes))
            .map_err(|error| Error::new("invalid_save", error.to_string()))?;
        Ok(serde_json::to_string_pretty(&save)?)
    })
}

pub fn json_to_sav(text: &str) -> Result<Vec<u8>> {
    if text.len() > document::MAX_SAVE_BYTES {
        return Err(Error::new("capacity", "The JSON document exceeds 64 MiB."));
    }
    save_operation(|| {
        let save: Save = serde_json::from_str(text)?;
        let mut output = Vec::new();
        save.write(&mut output)
            .map_err(|error| Error::new("write_save", error.to_string()))?;
        if output.len() > document::MAX_SAVE_BYTES {
            return Err(Error::new("capacity", "The save exceeds 64 MiB."));
        }
        Ok(output)
    })
}

pub fn decode_save(bytes: &[u8]) -> Result<String> {
    let text = sav_to_json(bytes)?;
    validate_document(&text)?;
    Ok(text)
}

pub fn encode_save(text: &str) -> Result<Vec<u8>> {
    let prepared = document::serialization_document(text)?;
    json_to_sav(&prepared)
}
