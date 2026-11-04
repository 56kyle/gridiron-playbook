use gridiron_playbook_core as core;
use wasm_bindgen::prelude::*;

fn js_error(error: core::error::Error) -> JsValue {
    JsValue::from_str(&error.json())
}
fn indices(text: &str) -> Result<Vec<usize>, JsValue> {
    serde_json::from_str(text).map_err(|error| js_error(error.into()))
}

#[wasm_bindgen]
pub fn new_document() -> Result<String, JsValue> {
    core::new_document().map_err(js_error)
}
#[wasm_bindgen]
pub fn validate_document(document: &str) -> Result<(), JsValue> {
    core::validate_document(document).map_err(js_error)
}
#[wasm_bindgen]
pub fn inspect_document(document: &str) -> Result<String, JsValue> {
    core::inspect_document(document).map_err(js_error)
}
#[wasm_bindgen]
pub fn formation_data() -> Result<String, JsValue> {
    core::formation_data().map_err(js_error)
}
#[wasm_bindgen]
pub fn apply_edit(document: &str, command_json: &str) -> Result<String, JsValue> {
    core::apply_edit(document, command_json).map_err(js_error)
}
#[wasm_bindgen]
pub fn transfer_plays(
    source: &str,
    target: &str,
    indices_json: &str,
    insertion: usize,
    mode: &str,
) -> Result<String, JsValue> {
    core::transfer_plays(source, target, indices_json, insertion, mode).map_err(js_error)
}
#[wasm_bindgen]
pub fn decode_save(bytes: &[u8]) -> Result<String, JsValue> {
    core::decode_save(bytes).map_err(js_error)
}
#[wasm_bindgen]
pub fn encode_save(document: &str) -> Result<Vec<u8>, JsValue> {
    core::encode_save(document).map_err(js_error)
}
#[wasm_bindgen]
pub fn encode_share(
    document: &str,
    indices_json: &str,
    kind: &str,
    precision: &str,
) -> Result<Vec<u8>, JsValue> {
    core::quickshare::encode_share(document, &indices(indices_json)?, kind, precision)
        .map_err(js_error)
}
#[wasm_bindgen]
pub fn inspect_share(data: &[u8]) -> Result<String, JsValue> {
    core::quickshare::inspect_share(data).map_err(js_error)
}
#[wasm_bindgen]
pub fn import_share(template_doc: &str, data: &[u8]) -> Result<String, JsValue> {
    core::quickshare::import_share(template_doc, data).map_err(js_error)
}
