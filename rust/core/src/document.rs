use crate::error::{Error, Result};
use crate::{block, formation};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub const MAX_SAVE_BYTES: usize = 64 * 1024 * 1024;
pub const MAX_PLAYS: usize = 2_000;
pub const MAX_ROUTES: usize = 256;
pub const MAX_POINTS_PER_PLAY: usize = 16_384;
pub const MAX_TOTAL_POINTS: usize = 200_000;
pub const MAX_COORDINATE: f64 = f64::MAX / (4. * MAX_POINTS_PER_PLAY as f64);

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Point {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Route {
    pub slot: u8,
    pub points: Vec<Point>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Play {
    pub formation_name: String,
    pub play_name: String,
    pub routes: Vec<Route>,
}

fn shape(message: &str) -> Error {
    Error::new("invalid_document", message)
}

pub fn plays(document: &Value) -> Result<&Vec<Value>> {
    document
        .pointer("/root/properties/CustomPlays_0")
        .and_then(Value::as_array)
        .ok_or_else(|| shape("The save is missing its CustomPlays array."))
}

pub fn replace_plays(document: &mut Value, values: Vec<Value>) -> Result<()> {
    let target = document
        .pointer_mut("/root/properties/CustomPlays_0")
        .ok_or_else(|| shape("The save is missing its CustomPlays array."))?;
    *target = Value::Array(values);
    Ok(())
}

pub fn validate_name(name: &str) -> Result<()> {
    if name.chars().count() > 1024 || name.contains('\0') {
        return Err(Error::new(
            "invalid_name",
            "Names must contain at most 1,024 characters without NUL.",
        ));
    }
    Ok(())
}

pub fn validate_point(point: &Point) -> Result<()> {
    if !(point.x.abs() <= MAX_COORDINATE && point.y.abs() <= MAX_COORDINATE && point.z.is_finite())
    {
        return Err(Error::new(
            "invalid_geometry",
            "Route coordinates must be finite and fit the field.",
        ));
    }
    Ok(())
}

pub fn point_from_raw(value: &Value) -> Result<Point> {
    let number = |key: &str| {
        value
            .get(key)
            .and_then(Value::as_f64)
            .ok_or_else(|| shape("A route point must have numeric X_0, Y_0, and Z_0 coordinates."))
    };
    let point = Point {
        x: number("X_0")?,
        y: number("Y_0")?,
        z: number("Z_0")?,
    };
    validate_point(&point)?;
    Ok(point)
}

pub fn point_to_raw(point: &Point) -> Value {
    json!({"X_0":point.x,"Y_0":point.y,"Z_0":point.z})
}

pub fn play_from_raw(value: &Value) -> Result<Play> {
    let formation_name = value
        .get("FormationName_0")
        .and_then(Value::as_str)
        .ok_or_else(|| shape("A play must have a formation name."))?
        .to_owned();
    let play_name = value
        .get("PlayName_0")
        .and_then(Value::as_str)
        .ok_or_else(|| shape("A play must have a play name."))?
        .to_owned();
    validate_name(&formation_name)?;
    validate_name(&play_name)?;
    let raw_routes = value
        .get("Routes_0")
        .and_then(Value::as_array)
        .ok_or_else(|| shape("A play must have a Routes_0 array."))?;
    if raw_routes.len() > MAX_ROUTES {
        return Err(Error::new("capacity", "A play exceeds the route limit."));
    }
    let mut routes = Vec::with_capacity(raw_routes.len());
    let mut count = 0;
    for raw in raw_routes {
        let slot = raw
            .get("Slot_0")
            .and_then(Value::as_u64)
            .and_then(|v| u8::try_from(v).ok())
            .ok_or_else(|| shape("A route slot must be an integer from 0 to 255."))?;
        let raw_points = raw
            .get("Points_0")
            .and_then(Value::as_array)
            .ok_or_else(|| shape("A route must have a Points_0 array."))?;
        count += raw_points.len();
        if count > MAX_POINTS_PER_PLAY {
            return Err(Error::new("capacity", "A play exceeds the waypoint limit."));
        }
        let points = raw_points
            .iter()
            .map(point_from_raw)
            .collect::<Result<_>>()?;
        routes.push(Route { slot, points });
    }
    Ok(Play {
        formation_name,
        play_name,
        routes,
    })
}

pub fn normalized_plays(document: &Value) -> Result<Vec<Play>> {
    let values = plays(document)?;
    if values.len() > MAX_PLAYS {
        return Err(Error::new(
            "capacity",
            "A playbook exceeds the 2,000-play limit.",
        ));
    }
    let parsed = values
        .iter()
        .map(play_from_raw)
        .collect::<Result<Vec<_>>>()?;
    if parsed
        .iter()
        .flat_map(|play| &play.routes)
        .map(|route| route.points.len())
        .sum::<usize>()
        > MAX_TOTAL_POINTS
    {
        return Err(Error::new(
            "capacity",
            "A playbook exceeds the waypoint limit.",
        ));
    }
    Ok(parsed)
}

pub fn play_to_raw(play: &Play) -> Value {
    json!({"FormationName_0":play.formation_name,"PlayName_0":play.play_name,
        "Routes_0":play.routes.iter().map(|route| json!({"Slot_0":route.slot,
            "Points_0":route.points.iter().map(point_to_raw).collect::<Vec<_>>() })).collect::<Vec<_>>()})
}

fn validate_value(document: &Value) -> Result<()> {
    if !document.get("header").is_some_and(Value::is_object)
        || !document
            .pointer("/schemas/schemas")
            .is_some_and(Value::is_object)
        || !document
            .pointer("/root/save_game_type")
            .is_some_and(Value::is_string)
        || !document
            .pointer("/root/properties/LastFormation_0")
            .is_some_and(Value::is_string)
        || !document
            .pointer("/root/properties/bLastWasDrawn_0")
            .is_some_and(Value::is_boolean)
        || !document
            .pointer("/root/properties/LastDrawnPlay_0")
            .is_some_and(Value::is_object)
    {
        return Err(shape(
            "The document is missing required Unreal playbook metadata.",
        ));
    }
    let _: uesave::Header = serde_json::from_value(document["header"].clone())
        .map_err(|error| shape(&format!("Invalid Unreal header: {error}")))?;
    let extra = document
        .get("extra")
        .and_then(Value::as_array)
        .ok_or_else(|| shape("The save must contain an extra-byte array."))?;
    if extra
        .iter()
        .any(|v| v.as_u64().is_none_or(|byte| byte > 255))
    {
        return Err(shape("Extra save bytes must be integers from 0 to 255."));
    }
    normalized_plays(document)?;
    Ok(())
}

pub fn parse_document(text: &str) -> Result<Value> {
    if text.len() > MAX_SAVE_BYTES {
        return Err(Error::new("capacity", "The JSON document exceeds 64 MiB."));
    }
    let value: Value = serde_json::from_str(text)?;
    validate_value(&value)?;
    Ok(value)
}

pub fn serialize_document(document: &Value) -> Result<String> {
    validate_value(document)?;
    let text = serde_json::to_string(document)?;
    if text.len() > MAX_SAVE_BYTES {
        return Err(Error::new("capacity", "The JSON document exceeds 64 MiB."));
    }
    Ok(text)
}

pub fn validate_document(text: &str) -> Result<()> {
    parse_document(text).map(|_| ())
}

pub fn new_document() -> Result<String> {
    let document: Value = serde_json::from_str(include_str!("blank.json"))?;
    serialize_document(&document)
}

pub fn inspect_document(text: &str) -> Result<String> {
    let document = parse_document(text)?;
    let inspected: Vec<Value> = normalized_plays(&document)?.into_iter().map(|play| {
        let routes: Vec<_> = play.routes.iter().map(|route| json!({
            "slot":route.slot,"points":route.points,
            "yards":block::route_yards_without_blocks(route,formation::start(&play.formation_name,route.slot)),
            "ends_with_block":block::ends_with_block(&route.points)
        })).collect();
        json!({"formation_name":play.formation_name,"play_name":play.play_name,"routes":routes})
    }).collect();
    Ok(serde_json::to_string(&json!({"plays":inspected}))?)
}

pub fn serialization_document(text: &str) -> Result<String> {
    let mut document = parse_document(text)?;
    let template: Value = serde_json::from_str(include_str!("blank.json"))?;
    let schemas = document
        .pointer_mut("/schemas/schemas")
        .and_then(Value::as_object_mut)
        .ok_or_else(|| shape("The document is missing its property schemas."))?;
    for (path, descriptor) in template["schemas"]["schemas"]
        .as_object()
        .expect("Bundled schema object")
    {
        schemas
            .entry(path.clone())
            .or_insert_with(|| descriptor.clone());
    }
    let mut properties = document
        .as_object_mut()
        .ok_or_else(|| shape("The document must be an object."))?
        .clone();
    let mut ordered = serde_json::Map::new();
    for key in ["header", "schemas", "root", "extra"] {
        if let Some(value) = properties.shift_remove(key) {
            ordered.insert(key.into(), value);
        }
    }
    ordered.extend(properties);
    serialize_document(&Value::Object(ordered))
}
