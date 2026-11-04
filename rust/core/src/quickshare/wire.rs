use super::blocks::{self, RouteBlock, BLOCK_POINTS};
use super::{
    invalid, too_large, validate_name, Precision, ShareKind, Snapshot, MAX_NAME_LENGTH, MAX_PLAYS,
    MAX_POINTS_PER_PLAY, MAX_ROUTES_PER_PLAY, MAX_SHARE_BYTES, MAX_TOTAL_POINTS,
};
use crate::document::{Play, Point, Route};
use crate::error::Result;
use crate::formation;
use flate2::write::ZlibEncoder;
use flate2::{Compression, Decompress, FlushDecompress, Status};
use std::io::Write;

const GRID_LIMIT: i64 = (1 << 30) - 1;
const MAX_DELTA_CODE: usize = 4 * GRID_LIMIT as usize;
const BLOCK_TABLE: u8 = 8;

fn uint(data: &mut Vec<u8>, mut value: usize) {
    while value >= 128 {
        data.push((value as u8 & 127) | 128);
        value >>= 7;
    }
    data.push(value as u8);
}

fn text(data: &mut Vec<u8>, value: &str) {
    uint(data, value.len());
    data.extend_from_slice(value.as_bytes());
}

fn route_mode(points: &[Point], precision: Precision) -> u8 {
    if precision == Precision::Exact || blocks::has_block_strokes(points) {
        return 0;
    }
    let mode = if precision == Precision::Millimeter {
        1
    } else {
        2
    };
    let limit = GRID_LIMIT as f64 / if mode == 1 { 10.0 } else { 1.0 };
    if points
        .iter()
        .any(|point| point.x.abs().max(point.y.abs()).max(point.z.abs()) > limit)
    {
        0
    } else {
        mode
    }
}

fn write_points(data: &mut Vec<u8>, points: &[Point], mode: u8, has_z: bool) {
    uint(data, points.len());
    let mut previous = [0i64; 3];
    let multiplier = if mode == 1 { 10.0 } else { 1.0 };
    for point in points {
        let coordinates = [point.x, point.y, point.z];
        for (axis, &coordinate) in coordinates[..if has_z { 3 } else { 2 }].iter().enumerate() {
            if mode == 0 {
                data.extend_from_slice(&coordinate.to_le_bytes());
            } else {
                let value = (coordinate * multiplier).round_ties_even() as i64;
                let delta = value - previous[axis];
                previous[axis] = value;
                uint(
                    data,
                    if delta >= 0 {
                        2 * delta
                    } else {
                        -2 * delta - 1
                    } as usize,
                );
            }
        }
    }
}

fn write_block(data: &mut Vec<u8>, points: &[Point], block: &RouteBlock, mode: u8) {
    uint(data, block.anchor);
    if mode != 0 {
        data.push(2);
        data.extend_from_slice(&blocks::compact_heading(block.direction).to_le_bytes());
    } else {
        let infer = blocks::inferred_direction(points, block.anchor).is_some_and(|direction| {
            direction.0.to_bits() == block.direction.0.to_bits()
                && direction.1.to_bits() == block.direction.1.to_bits()
        });
        if infer {
            data.push(0);
        } else {
            data.push(1);
            data.extend_from_slice(&block.direction.0.to_le_bytes());
            data.extend_from_slice(&block.direction.1.to_le_bytes());
        }
    }
}

fn write_route(data: &mut Vec<u8>, route: &Route, precision: Precision, start: Option<(f64, f64)>) {
    let (points, blocks) = blocks::split_blocks(&route.points, start);
    let mode = route_mode(&points, precision);
    let has_z = if mode == 0 {
        points
            .iter()
            .any(|point| point.z != 0.0 || point.z.is_sign_negative())
    } else {
        let multiplier = if mode == 1 { 10.0 } else { 1.0 };
        points
            .iter()
            .any(|point| (point.z * multiplier).round_ties_even() != 0.0)
    };
    let flags = (2 * mode + u8::from(has_z)) | if blocks.is_empty() { 0 } else { BLOCK_TABLE };
    data.extend_from_slice(&[route.slot, flags]);
    write_points(data, &points, mode, has_z);
    if !blocks.is_empty() {
        uint(data, blocks.len());
        for block in &blocks {
            write_block(data, &points, block, mode);
        }
    }
}

pub(super) fn encode(snapshot: &Snapshot, precision: Precision) -> Result<Vec<u8>> {
    let mut data = b"GQS\x02".to_vec();
    data.push(u8::from(snapshot.kind == ShareKind::Playbook));
    let mut formations: Vec<&str> = Vec::new();
    for play in &snapshot.plays {
        if !formations.contains(&play.formation_name.as_str()) {
            formations.push(&play.formation_name);
        }
    }
    uint(&mut data, formations.len());
    for formation in &formations {
        text(&mut data, formation);
    }
    uint(&mut data, snapshot.plays.len());
    for play in &snapshot.plays {
        let formation_index = formations
            .iter()
            .position(|&name| name == play.formation_name)
            .ok_or_else(|| invalid("The Quickshare formation table is incomplete."))?;
        uint(&mut data, formation_index);
        text(&mut data, &play.play_name);
        uint(&mut data, play.routes.len());
        for route in &play.routes {
            write_route(
                &mut data,
                route,
                precision,
                formation::start(&play.formation_name, route.slot),
            );
        }
        if data.len() > MAX_SHARE_BYTES {
            return Err(too_large());
        }
    }
    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::best());
    encoder
        .write_all(&data)
        .map_err(|error| invalid(format!("Could not compress Quickshare data: {error}")))?;
    let compressed = encoder
        .finish()
        .map_err(|error| invalid(format!("Could not finish Quickshare data: {error}")))?;
    if compressed.len() > MAX_SHARE_BYTES {
        return Err(too_large());
    }
    Ok(compressed)
}

fn inflate(data: &[u8]) -> Result<Vec<u8>> {
    if data.len() > MAX_SHARE_BYTES {
        return Err(too_large());
    }
    let mut decoder = Decompress::new(true);
    let mut raw = Vec::new();
    let mut buffer = [0u8; 8192];
    loop {
        let before_in = decoder.total_in();
        let before_out = decoder.total_out();
        let available = buffer.len().min(MAX_SHARE_BYTES + 1 - raw.len());
        let status = decoder
            .decompress(
                &data[before_in as usize..],
                &mut buffer[..available],
                FlushDecompress::None,
            )
            .map_err(|error| invalid(format!("Invalid compressed Quickshare data: {error}")))?;
        let emitted = (decoder.total_out() - before_out) as usize;
        raw.extend_from_slice(&buffer[..emitted]);
        if raw.len() > MAX_SHARE_BYTES {
            return Err(too_large());
        }
        if status == Status::StreamEnd {
            if decoder.total_in() as usize != data.len() {
                return Err(invalid(
                    "Expected one complete Quickshare payload without trailing bytes.",
                ));
            }
            return Ok(raw);
        }
        if decoder.total_in() == before_in && emitted == 0 {
            return Err(invalid("The compressed Quickshare data is incomplete."));
        }
    }
}

struct Reader<'a> {
    data: &'a [u8],
    cursor: usize,
    points_left: usize,
}

impl<'a> Reader<'a> {
    fn new(data: &'a [u8]) -> Self {
        Self {
            data,
            cursor: 0,
            points_left: MAX_TOTAL_POINTS,
        }
    }

    fn take(&mut self, size: usize) -> Result<&'a [u8]> {
        let end = self
            .cursor
            .checked_add(size)
            .ok_or_else(|| invalid("Invalid Quickshare byte count."))?;
        let bytes = self
            .data
            .get(self.cursor..end)
            .ok_or_else(|| invalid("The Quickshare data is incomplete."))?;
        self.cursor = end;
        Ok(bytes)
    }

    fn byte(&mut self) -> Result<u8> {
        Ok(self.take(1)?[0])
    }

    fn uint(&mut self, limit: usize) -> Result<usize> {
        let mut value = 0u64;
        let bits = usize::BITS - limit.leading_zeros();
        for shift in (0..=bits).step_by(7) {
            let byte = self.byte()?;
            value |= u64::from(byte & 127)
                .checked_shl(shift)
                .ok_or_else(|| invalid("Invalid Quickshare count."))?;
            if byte < 128 {
                if value <= limit as u64 && (shift == 0 || byte != 0) {
                    return Ok(value as usize);
                }
                break;
            }
        }
        Err(invalid("Invalid Quickshare count or coordinate."))
    }

    fn text(&mut self) -> Result<String> {
        let size = self.uint(4 * MAX_NAME_LENGTH)?;
        let value = std::str::from_utf8(self.take(size)?)
            .map_err(|_| invalid("Quickshare names must be valid UTF-8."))?;
        validate_name(value)?;
        Ok(value.to_owned())
    }

    fn float(&mut self) -> Result<f64> {
        let mut bytes = [0; 8];
        bytes.copy_from_slice(self.take(8)?);
        Ok(f64::from_le_bytes(bytes))
    }

    fn literal_points(&mut self, flags: u8, count: usize) -> Result<Vec<Point>> {
        let mode = flags >> 1;
        let has_z = flags & 1 != 0;
        let mut previous = [0i64; 3];
        let mut points = Vec::with_capacity(count);
        for _ in 0..count {
            let mut coordinates = [0.0; 3];
            for axis in 0..if has_z { 3 } else { 2 } {
                if mode == 0 {
                    coordinates[axis] = self.float()?;
                } else {
                    let code = self.uint(MAX_DELTA_CODE)? as i64;
                    previous[axis] += (code >> 1) ^ -(code & 1);
                    if previous[axis].abs() > GRID_LIMIT {
                        return Err(invalid("Quickshare grid coordinate is out of range."));
                    }
                    coordinates[axis] = previous[axis] as f64 / if mode == 1 { 10.0 } else { 1.0 };
                }
            }
            points.push(Point {
                x: coordinates[0],
                y: coordinates[1],
                z: coordinates[2],
            });
        }
        Ok(points)
    }

    fn block_direction(
        &mut self,
        points: &[Point],
        anchor: usize,
        mode: u8,
    ) -> Result<blocks::Direction> {
        match (mode, self.byte()?) {
            (1 | 2, 2) => {
                let bytes = self.take(2)?;
                Ok(blocks::heading_direction(u16::from_le_bytes([
                    bytes[0], bytes[1],
                ])))
            }
            (0, 0) => blocks::inferred_direction(points, anchor)
                .ok_or_else(|| invalid("Invalid inferred Quickshare block direction.")),
            (0, 1) => {
                let direction = (self.float()?, self.float()?);
                if !blocks::valid_direction(direction) {
                    return Err(invalid("Invalid Quickshare block direction."));
                }
                Ok(direction)
            }
            _ => Err(invalid("Invalid Quickshare block instruction.")),
        }
    }

    fn blocks(&mut self, points: &[Point], mode: u8, remaining: usize) -> Result<Vec<RouteBlock>> {
        let count = self.uint(remaining.min(self.points_left) / BLOCK_POINTS)?;
        if points.is_empty() || count == 0 {
            return Err(invalid("Empty Quickshare block table or route."));
        }
        self.points_left -= count * BLOCK_POINTS;
        let mut blocks: Vec<RouteBlock> = Vec::with_capacity(count);
        for _ in 0..count {
            let anchor = self.uint(points.len() - 1)?;
            if blocks.last().is_some_and(|block| anchor < block.anchor) {
                return Err(invalid("Quickshare block anchors must follow route order."));
            }
            let direction = self.block_direction(points, anchor, mode)?;
            blocks.push(RouteBlock { anchor, direction });
        }
        Ok(blocks)
    }

    fn route(&mut self, remaining: usize, version: u8) -> Result<Route> {
        let slot = self.byte()?;
        let mut flags = self.byte()?;
        let has_blocks = version == 2 && flags & BLOCK_TABLE != 0;
        if has_blocks {
            flags ^= BLOCK_TABLE;
        }
        if flags > 5 {
            return Err(invalid("Unknown Quickshare coordinate format."));
        }
        let count = self.uint(remaining.min(self.points_left))?;
        self.points_left -= count;
        let mut points = self.literal_points(flags, count)?;
        if has_blocks {
            let blocks = self.blocks(&points, flags >> 1, remaining - count)?;
            points = blocks::expand_blocks(&points, &blocks);
        }
        Ok(Route { slot, points })
    }

    fn play(&mut self, formations: &[String], version: u8) -> Result<Play> {
        let formation_name = formations[self.uint(formations.len() - 1)?].clone();
        let play_name = self.text()?;
        let count = self.uint(MAX_ROUTES_PER_PLAY)?;
        let mut remaining = MAX_POINTS_PER_PLAY;
        let mut routes = Vec::with_capacity(count);
        for _ in 0..count {
            let route = self.route(remaining, version)?;
            remaining -= route.points.len();
            routes.push(route);
        }
        Ok(Play {
            formation_name,
            play_name,
            routes,
        })
    }
}

pub(super) fn decode(data: &[u8]) -> Result<Snapshot> {
    let raw = inflate(data)?;
    let mut reader = Reader::new(&raw);
    if reader.take(3)? != b"GQS" {
        return Err(invalid("Unknown Quickshare file format."));
    }
    let version = reader.byte()?;
    if version != 1 && version != 2 {
        return Err(invalid("Unknown Quickshare file version."));
    }
    let kind = match reader.byte()? {
        0 => ShareKind::Play,
        1 => ShareKind::Playbook,
        _ => return Err(invalid("Unknown Quickshare selection.")),
    };
    let count = reader.uint(MAX_PLAYS)?;
    if count == 0 {
        return Err(invalid("The Quickshare formation table is empty."));
    }
    let formations = (0..count)
        .map(|_| reader.text())
        .collect::<Result<Vec<_>>>()?;
    let count = reader.uint(if kind == ShareKind::Play {
        1
    } else {
        MAX_PLAYS
    })?;
    let plays = (0..count)
        .map(|_| reader.play(&formations, version))
        .collect::<Result<Vec<_>>>()?;
    if reader.cursor != raw.len() {
        return Err(invalid("Unexpected trailing Quickshare data."));
    }
    Ok(Snapshot {
        version: 1,
        kind,
        plays,
    })
}
