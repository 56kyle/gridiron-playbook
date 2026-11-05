use gridiron_playbook_core as core;
use serde_json::{json, Value};

fn document() -> String {
    let mut value: Value = serde_json::from_str(&core::new_document().unwrap()).unwrap();
    value["root"]["properties"]["CustomPlays_0"] = json!([{
        "FormationName_0":"Twins Right", "PlayName_0":"Groups", "FuturePlayField":123,
        "Routes_0":[
            {"Slot_0":5,"FutureRouteField":"keep","Points_0":[
                {"X_0":100.0,"Y_0":-0.0,"Z_0":-0.0,"Note":"first"},
                {"X_0":200.0,"Y_0":300.0,"Z_0":12.0},
                {"X_0":400.0,"Y_0":500.0,"Z_0":15.0}
            ]},
            {"Slot_0":6,"Points_0":[
                {"X_0":700.0,"Y_0":800.0,"Z_0":30.0},
                {"X_0":900.0,"Y_0":1000.0,"Z_0":40.0}
            ]}
        ]
    }]);
    value.to_string()
}

fn apply(document: &str, command: Value) -> Value {
    serde_json::from_str(&core::apply_edit(document, &command.to_string()).unwrap()).unwrap()
}

#[test]
fn move_points_translates_only_selected_nodes_and_preserves_metadata() {
    let source = document();
    let actual = apply(
        &source,
        json!({"type":"move_points","play_index":0,
        "points":[{"route_index":1,"point_index":1},{"route_index":0,"point_index":0}],"dx":125.0,"dy":-20.0}),
    );
    let mut expected: Value = serde_json::from_str(&source).unwrap();
    let routes = &mut expected["root"]["properties"]["CustomPlays_0"][0]["Routes_0"];
    routes[0]["Points_0"][0]["X_0"] = json!(225.0);
    routes[0]["Points_0"][0]["Y_0"] = json!(-20.0);
    routes[1]["Points_0"][1]["X_0"] = json!(1025.0);
    routes[1]["Points_0"][1]["Y_0"] = json!(980.0);
    assert_eq!(actual.to_string(), expected.to_string());
}

#[test]
fn move_points_preserves_signed_zero_on_an_unchanged_axis() {
    let actual = apply(
        &document(),
        json!({"type":"move_points","play_index":0,
        "points":[{"route_index":0,"point_index":0}],"dx":1.0,"dy":0.0}),
    );
    let point = &actual["root"]["properties"]["CustomPlays_0"][0]["Routes_0"][0]["Points_0"][0];
    assert_eq!(
        point["Y_0"].as_f64().unwrap().to_bits(),
        (-0.0f64).to_bits()
    );
    assert_eq!(
        point["Z_0"].as_f64().unwrap().to_bits(),
        (-0.0f64).to_bits()
    );
}

#[test]
fn move_points_with_zero_offset_preserves_original_document_text() {
    let source =
        serde_json::to_string_pretty(&serde_json::from_str::<Value>(&document()).unwrap()).unwrap();
    let result = core::apply_edit(
        &source,
        &json!({"type":"move_points","play_index":0,
        "points":[{"route_index":0,"point_index":0}],"dx":0.0,"dy":0.0})
        .to_string(),
    )
    .unwrap();
    assert_eq!(result, source);
}

#[test]
fn delete_points_preserves_order_and_unselected_data_across_routes() {
    let source = document();
    let actual = apply(
        &source,
        json!({"type":"delete_points","play_index":0,"points":[
            {"route_index":0,"point_index":2},{"route_index":1,"point_index":0},{"route_index":0,"point_index":1}
        ]}),
    );
    let mut expected: Value = serde_json::from_str(&source).unwrap();
    let routes = &mut expected["root"]["properties"]["CustomPlays_0"][0]["Routes_0"];
    routes[0]["Points_0"].as_array_mut().unwrap().truncate(1);
    routes[1]["Points_0"].as_array_mut().unwrap().remove(0);
    assert_eq!(actual.to_string(), expected.to_string());
}

#[test]
fn delete_points_removes_fully_selected_routes_without_reindexing_other_edits() {
    let source = document();
    let actual = apply(
        &source,
        json!({"type":"delete_points","play_index":0,"points":[
            {"route_index":0,"point_index":0},{"route_index":0,"point_index":1},{"route_index":0,"point_index":2},
            {"route_index":1,"point_index":1}
        ]}),
    );
    let mut expected: Value = serde_json::from_str(&source).unwrap();
    let routes = expected["root"]["properties"]["CustomPlays_0"][0]["Routes_0"]
        .as_array_mut()
        .unwrap();
    routes[1]["Points_0"].as_array_mut().unwrap().remove(1);
    routes.remove(0);
    assert_eq!(actual.to_string(), expected.to_string());
}

#[test]
fn node_edits_reject_empty_duplicate_and_out_of_range_selections() {
    for (points, code) in [
        (json!([]), "invalid_selection"),
        (
            json!([{"route_index":0,"point_index":0},{"route_index":0,"point_index":0}]),
            "invalid_selection",
        ),
        (
            json!([{"route_index":0,"point_index":0},{"route_index":2,"point_index":0}]),
            "invalid_index",
        ),
        (
            json!([{"route_index":0,"point_index":0},{"route_index":1,"point_index":2}]),
            "invalid_index",
        ),
    ] {
        for kind in ["delete_points", "move_points"] {
            let mut command = json!({"type":kind,"play_index":0,"points":points});
            if kind == "move_points" {
                command["dx"] = json!(1.0);
                command["dy"] = json!(2.0);
            }
            assert_eq!(
                core::apply_edit(&document(), &command.to_string())
                    .unwrap_err()
                    .code,
                code
            );
        }
    }
}

#[test]
fn move_points_rejects_unrepresentable_geometry() {
    let result = core::apply_edit(
        &document(),
        &json!({"type":"move_points","play_index":0,
        "points":[{"route_index":0,"point_index":0}],"dx":1e308,"dy":0.0})
        .to_string(),
    );
    assert_eq!(result.unwrap_err().code, "invalid_geometry");
}

#[test]
fn delete_points_rejects_partial_unknown_routes_but_allows_complete_removal() {
    let mut source: Value = serde_json::from_str(&document()).unwrap();
    source["root"]["properties"]["CustomPlays_0"][0]["FormationName_0"] = json!("Unknown");
    let source = source.to_string();
    let partial =
        json!({"type":"delete_points","play_index":0,"points":[{"route_index":1,"point_index":0}]});
    assert_eq!(
        core::apply_edit(&source, &partial.to_string())
            .unwrap_err()
            .code,
        "invalid_geometry"
    );
    let removed = apply(
        &source,
        json!({"type":"delete_points","play_index":0,"points":[
            {"route_index":1,"point_index":0},{"route_index":1,"point_index":1}
        ]}),
    );
    assert_eq!(
        removed["root"]["properties"]["CustomPlays_0"][0]["Routes_0"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
