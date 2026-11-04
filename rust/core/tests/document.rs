use gridiron_playbook_core as core;
use serde_json::{json, Value};

fn fixture() -> String {
    include_str!("../../../data/GridIronCustomPlays.json").into()
}
fn command(document: &str, edit: Value) -> String {
    core::apply_edit(document, &edit.to_string()).unwrap()
}
fn names(document: &str) -> Vec<String> {
    let inspected: Value =
        serde_json::from_str(&core::inspect_document(document).unwrap()).unwrap();
    inspected["plays"]
        .as_array()
        .unwrap()
        .iter()
        .map(|play| play["play_name"].as_str().unwrap().into())
        .collect()
}
fn point_document() -> String {
    let mut value: Value = serde_json::from_str(&core::new_document().unwrap()).unwrap();
    value["root"]["properties"]["CustomPlays_0"] = json!([{
        "FormationName_0":"Twins Right", "PlayName_0":"Test", "CustomField":{"large":18446744073709551615u64},
        "Routes_0":[{"Slot_0":0,"Points_0":[{"X_0":-0.0,"Y_0":-0.0,"Z_0":-0.0,"Note":"keep"},{"X_0":100.0,"Y_0":200.0,"Z_0":9.0}]}]
    }]);
    value["header"]["unrecognized"] = json!(18446744073709551615u64);
    value.to_string()
}

#[test]
fn blank_template_roundtrips_through_uesave() {
    let original = core::new_document().unwrap();
    assert!(names(&original).is_empty());
    let bytes = core::encode_save(&original).unwrap();
    assert_eq!(&bytes[..4], b"GVAS");
    let decoded = core::decode_save(&bytes).unwrap();
    let original_value: Value = serde_json::from_str(&original).unwrap();
    let decoded_value: Value = serde_json::from_str(&decoded).unwrap();
    for key in ["header", "root", "extra"] {
        assert_eq!(original_value[key], decoded_value[key]);
    }
    assert_eq!(core::encode_save(&decoded).unwrap(), bytes);
    let edited = command(
        &decoded,
        json!({"type":"create_play","formation_name":"Twins Right","play_name":"First"}),
    );
    let edited = command(
        &edited,
        json!({"type":"add_route","play_index":0,"slot":0,"points":[{"x":100.,"y":0.,"z":0.}]}),
    );
    let saved = core::decode_save(&core::encode_save(&edited).unwrap()).unwrap();
    assert_eq!(names(&saved), ["First"]);
}

#[test]
fn inspect_preserves_input_and_supplies_geometry() {
    let original = fixture();
    let data: Value = serde_json::from_str(&core::inspect_document(&original).unwrap()).unwrap();
    assert!(!data["plays"].as_array().unwrap().is_empty());
    let route = &data["plays"][0]["routes"][0];
    assert!(route["yards"].as_f64().unwrap() >= 0.);
    assert!(route["ends_with_block"].is_boolean());
}

#[test]
fn rename_preserves_unknown_data_and_signed_zero() {
    let original = point_document();
    let changed = command(
        &original,
        json!({"type":"rename_play","play_index":0,"play_name":"Renamed"}),
    );
    let mut expected: Value = serde_json::from_str(&original).unwrap();
    expected["root"]["properties"]["CustomPlays_0"][0]["PlayName_0"] = json!("Renamed");
    assert_eq!(changed, expected.to_string());
    assert!(changed.contains("18446744073709551615"));
    assert!(changed.contains("\"X_0\":-0.0"));
    assert!(changed.contains("\"Y_0\":-0.0"));
}

#[test]
fn noop_preserves_original_json_text() {
    let original =
        serde_json::to_string_pretty(&serde_json::from_str::<Value>(&point_document()).unwrap())
            .unwrap();
    let result = command(
        &original,
        json!({"type":"rename_play","play_index":0,"play_name":"Test"}),
    );
    assert_eq!(result, original);
}

#[test]
fn create_and_duplicate_insert_at_top() {
    let original = fixture();
    let added = command(
        &original,
        json!({"type":"create_play","formation_name":"Twins Right","play_name":"New"}),
    );
    assert_eq!(names(&added)[0], "New");
    assert_eq!(&names(&added)[1..], names(&original));
    let duplicated = command(
        &added,
        json!({"type":"duplicate_play","play_index":1,"play_name":"Copy"}),
    );
    assert_eq!(&names(&duplicated)[..2], ["Copy", "New"]);
}

#[test]
fn reorder_uses_source_order_and_original_insertion_boundary() {
    let mut book = core::new_document().unwrap();
    for name in ["D", "C", "B", "A"] {
        book = command(
            &book,
            json!({"type":"create_play","formation_name":"Twins Right","play_name":name}),
        );
    }
    let changed = command(
        &book,
        json!({"type":"reorder_plays","indices":[2,0],"insertion":4}),
    );
    assert_eq!(names(&changed), ["B", "D", "A", "C"]);
    let deleted = command(&changed, json!({"type":"delete_plays","indices":[2,0]}));
    assert_eq!(names(&deleted), ["D", "C"]);
}

#[test]
fn transfers_preserve_destination_metadata_and_return_both_documents() {
    let source = point_document();
    let target = core::new_document().unwrap();
    let result: Value =
        serde_json::from_str(&core::transfer_plays(&source, &target, "[0]", 0, "move").unwrap())
            .unwrap();
    let moved_source = result["source"].as_str().unwrap();
    let moved_target = result["target"].as_str().unwrap();
    assert!(names(moved_source).is_empty());
    assert_eq!(names(moved_target), ["Test"]);
    let original: Value = serde_json::from_str(&target).unwrap();
    let moved: Value = serde_json::from_str(moved_target).unwrap();
    assert_eq!(original["header"], moved["header"]);
    assert!(moved_target.contains("\"X_0\":-0.0"));
    assert!(moved_target.contains("\"CustomField\""));
    let copied: Value =
        serde_json::from_str(&core::transfer_plays(&source, &target, "[0]", 0, "copy").unwrap())
            .unwrap();
    assert_eq!(copied["source"].as_str().unwrap(), source);
}

#[test]
fn edits_reject_invalid_selection_without_mutating_document() {
    let original = fixture();
    for edit in [
        json!({"type":"delete_plays","indices":[0,0]}),
        json!({"type":"reorder_plays","indices":[],"insertion":0}),
        json!({"type":"rename_play","play_index":99999,"play_name":"x"}),
    ] {
        assert!(core::apply_edit(&original, &edit.to_string()).is_err());
    }
    assert_eq!(original, fixture());
}

#[test]
fn point_moves_preserve_height_and_unknown_fields() {
    let changed = command(
        &point_document(),
        json!({"type":"move_point","play_index":0,"route_index":0,"point_index":0,"x":12.0,"y":34.0}),
    );
    let value: Value = serde_json::from_str(&changed).unwrap();
    let point = &value["root"]["properties"]["CustomPlays_0"][0]["Routes_0"][0]["Points_0"][0];
    assert_eq!(point["X_0"], 12.0);
    assert_eq!(point["Y_0"], 34.0);
    assert!(point["Z_0"].as_f64().unwrap().is_sign_negative());
    assert_eq!(point["Note"], "keep");
}

#[test]
fn inserted_point_interpolates_height() {
    let changed = command(
        &point_document(),
        json!({"type":"insert_point","play_index":0,"route_index":0,"point_index":1,"x":50.0,"y":100.0}),
    );
    let value: Value = serde_json::from_str(&core::inspect_document(&changed).unwrap()).unwrap();
    assert!(
        (value["plays"][0]["routes"][0]["points"][1]["z"]
            .as_f64()
            .unwrap()
            - 4.5)
            .abs()
            < 1e-12
    );
}

#[test]
fn block_does_not_add_yardage_and_can_continue() {
    let original = point_document();
    let before: Value = serde_json::from_str(&core::inspect_document(&original).unwrap()).unwrap();
    let blocked = command(
        &original,
        json!({"type":"add_block","play_index":0,"route_index":0,"point_index":1}),
    );
    let after: Value = serde_json::from_str(&core::inspect_document(&blocked).unwrap()).unwrap();
    assert_eq!(
        before["plays"][0]["routes"][0]["yards"],
        after["plays"][0]["routes"][0]["yards"]
    );
    assert_eq!(after["plays"][0]["routes"][0]["ends_with_block"], true);
    let continued = command(
        &blocked,
        json!({"type":"insert_point","play_index":0,"route_index":0,"point_index":30,"x":200.,"y":200.}),
    );
    let continued: Value =
        serde_json::from_str(&core::inspect_document(&continued).unwrap()).unwrap();
    assert_eq!(continued["plays"][0]["routes"][0]["ends_with_block"], false);
}

#[test]
fn unknown_formation_routes_need_two_points() {
    let empty = command(
        &core::new_document().unwrap(),
        json!({"type":"create_play","formation_name":"Future","play_name":"Unknown"}),
    );
    let error = core::apply_edit(
        &empty,
        &json!({"type":"add_route","play_index":0,"slot":255,"points":[{"x":0.,"y":0.,"z":0.}]})
            .to_string(),
    )
    .unwrap_err();
    assert_eq!(error.code, "invalid_geometry");
}

#[test]
fn malformed_document_reports_machine_category() {
    assert_eq!(
        core::validate_document("{").unwrap_err().code,
        "invalid_json"
    );
    assert_eq!(
        core::validate_document("{}").unwrap_err().code,
        "invalid_document"
    );
}

#[test]
fn flip_changes_roles_and_geometry_without_dropping_metadata() {
    let flipped = command(
        &point_document(),
        json!({"type":"flip_play","play_index":0}),
    );
    let view: Value = serde_json::from_str(&core::inspect_document(&flipped).unwrap()).unwrap();
    assert_eq!(view["plays"][0]["formation_name"], "Twins Left");
    assert_eq!(view["plays"][0]["routes"][0]["points"][1]["y"], -200.);
    assert!(flipped.contains("18446744073709551615"));
}
