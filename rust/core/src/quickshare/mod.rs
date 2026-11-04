mod blocks;
mod wire;

use crate::document::{self, Play};
use crate::error::{Error, Result};
use serde::{Deserialize, Serialize};
use serde_json::json;

pub const MAX_SHARE_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_PLAYS: usize = 2000;
pub const MAX_ROUTES_PER_PLAY: usize = 256;
pub const MAX_POINTS_PER_PLAY: usize = 16384;
pub const MAX_TOTAL_POINTS: usize = 200000;
pub const MAX_NAME_LENGTH: usize = 1024;
const MAX_FIELD_COORDINATE: f64 = f64::MAX / (4 * MAX_POINTS_PER_PLAY) as f64;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ShareKind {
    Play,
    Playbook,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Precision {
    Exact,
    Millimeter,
    Centimeter,
}

impl Precision {
    pub fn parse(value: &str) -> Result<Self> {
        match value {
            "exact" => Ok(Self::Exact),
            "1mm" => Ok(Self::Millimeter),
            "1cm" => Ok(Self::Centimeter),
            _ => Err(invalid("Unknown Quickshare precision.")),
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub version: u8,
    pub kind: ShareKind,
    pub plays: Vec<Play>,
}

pub(super) fn invalid(message: impl Into<String>) -> Error {
    Error::new("invalid_share", message)
}

pub(super) fn too_large() -> Error {
    Error::new("share_too_large", "The Quickshare size limit is 16 MiB.")
}

pub(super) fn validate_name(name: &str) -> Result<()> {
    if name.chars().count() > MAX_NAME_LENGTH || name.contains('\0') {
        return Err(invalid(
            "Quickshare names must be valid text of at most 1024 characters without NUL.",
        ));
    }
    Ok(())
}

pub fn validate_snapshot(snapshot: &Snapshot) -> Result<()> {
    if snapshot.version != 1
        || snapshot.plays.is_empty()
        || snapshot.plays.len() > MAX_PLAYS
        || (snapshot.kind == ShareKind::Play && snapshot.plays.len() != 1)
    {
        return Err(invalid("Invalid Quickshare version or play count."));
    }
    let mut total = 0;
    for play in &snapshot.plays {
        validate_name(&play.play_name)?;
        validate_name(&play.formation_name)?;
        if play.routes.len() > MAX_ROUTES_PER_PLAY {
            return Err(invalid("A play exceeds the Quickshare route limit."));
        }
        let count: usize = play.routes.iter().map(|route| route.points.len()).sum();
        if count > MAX_POINTS_PER_PLAY {
            return Err(invalid("A play exceeds the Quickshare waypoint limit."));
        }
        total += count;
        if total > MAX_TOTAL_POINTS {
            return Err(invalid(
                "This playbook exceeds the Quickshare waypoint limit.",
            ));
        }
        for point in play.routes.iter().flat_map(|route| &route.points) {
            if !(point.x.abs() <= MAX_FIELD_COORDINATE
                && point.y.abs() <= MAX_FIELD_COORDINATE
                && point.z.is_finite())
            {
                return Err(invalid(
                    "Quickshare coordinates must be finite and fit the field diagram.",
                ));
            }
        }
    }
    Ok(())
}

pub fn encode_snapshot(snapshot: &Snapshot, precision: Precision) -> Result<Vec<u8>> {
    validate_snapshot(snapshot)?;
    wire::encode(snapshot, precision)
}

pub fn decode_share(data: &[u8]) -> Result<Snapshot> {
    let snapshot = wire::decode(data)?;
    validate_snapshot(&snapshot)?;
    Ok(snapshot)
}

pub fn encode_share(
    document: &str,
    indices: &[usize],
    kind: &str,
    precision: &str,
) -> Result<Vec<u8>> {
    let raw = document::parse_document(document)?;
    let available = document::normalized_plays(&raw)?;
    let kind = match kind {
        "play" => ShareKind::Play,
        "playbook" => ShareKind::Playbook,
        _ => return Err(invalid("Unknown Quickshare selection.")),
    };
    let mut selected = indices.to_vec();
    selected.sort_unstable();
    if selected.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(invalid("Select each play only once."));
    }
    let plays = selected
        .iter()
        .map(|&index| {
            available
                .get(index)
                .cloned()
                .ok_or_else(|| invalid("A selected play is no longer available."))
        })
        .collect::<Result<Vec<_>>>()?;
    encode_snapshot(
        &Snapshot {
            version: 1,
            kind,
            plays,
        },
        Precision::parse(precision)?,
    )
}

pub fn inspect_share(data: &[u8]) -> Result<String> {
    let snapshot = decode_share(data)?;
    let plays = snapshot.plays.iter().map(|play| {
        let routes = play.routes.iter().map(|route| json!({
            "slot": route.slot,
            "points": route.points,
            "yards": crate::block::route_yards_without_blocks(route, crate::formation::start(&play.formation_name, route.slot)),
            "ends_with_block": crate::block::ends_with_block(&route.points),
        })).collect::<Vec<_>>();
        json!({"formation_name": play.formation_name, "play_name": play.play_name, "routes": routes})
    }).collect::<Vec<_>>();
    serde_json::to_string(
        &json!({"version": snapshot.version, "kind": snapshot.kind, "plays": plays}),
    )
    .map_err(|error| invalid(error.to_string()))
}

pub fn import_share(template: &str, data: &[u8]) -> Result<String> {
    let snapshot = decode_share(data)?;
    let mut target = document::parse_document(template)?;
    let mut imported = snapshot
        .plays
        .iter()
        .map(document::play_to_raw)
        .collect::<Vec<_>>();
    if snapshot.kind == ShareKind::Play {
        imported.extend(document::plays(&target)?.iter().cloned());
    }
    document::replace_plays(&mut target, imported)?;
    let encoded = document::serialize_document(&target)?;
    serde_json::to_string(&json!({"kind": snapshot.kind, "document": encoded}))
        .map_err(|error| invalid(error.to_string()))
}
