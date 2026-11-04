use flate2::{write::ZlibEncoder, Compression};
use gridiron_playbook_core::document::{Play, Point, Route};
use gridiron_playbook_core::quickshare::{
    decode_share, encode_snapshot, Precision, ShareKind, Snapshot, MAX_SHARE_BYTES,
};
use std::io::Write;

fn xyz_bits(snapshot: &Snapshot) -> Vec<[u64; 3]> {
    snapshot
        .plays
        .iter()
        .flat_map(|play| &play.routes)
        .flat_map(|route| &route.points)
        .map(|point| [point.x.to_bits(), point.y.to_bits(), point.z.to_bits()])
        .collect()
}

fn assert_content(actual: &Snapshot, expected: &Snapshot, exact: bool) {
    assert_eq!(actual.kind, expected.kind);
    assert_eq!(actual.plays.len(), expected.plays.len());
    for (actual, expected) in actual.plays.iter().zip(&expected.plays) {
        assert_eq!(actual.formation_name, expected.formation_name);
        assert_eq!(actual.play_name, expected.play_name);
        assert_eq!(actual.routes.len(), expected.routes.len());
        for (actual, expected) in actual.routes.iter().zip(&expected.routes) {
            assert_eq!(actual.slot, expected.slot);
            assert_eq!(actual.points.len(), expected.points.len());
            for (actual, expected) in actual.points.iter().zip(&expected.points) {
                for (actual, expected) in [
                    (actual.x, expected.x),
                    (actual.y, expected.y),
                    (actual.z, expected.z),
                ] {
                    if exact {
                        assert_eq!(actual.to_bits(), expected.to_bits());
                    } else {
                        assert!((actual - expected).abs() <= 1e-9, "{actual} != {expected}");
                    }
                }
            }
        }
    }
}

macro_rules! python_fixture {
    ($name:ident, $file:literal, $exact:expr) => {
        #[test]
        fn $name() {
            let bytes = include_bytes!(concat!("fixtures/quickshare/", $file, ".gridironshare"));
            let expected: Snapshot = serde_json::from_str(include_str!(concat!(
                "fixtures/quickshare/",
                $file,
                ".json"
            )))
            .unwrap();
            let decoded = decode_share(bytes).unwrap();
            assert_content(&decoded, &expected, $exact);
            let exact =
                decode_share(&encode_snapshot(&decoded, Precision::Exact).unwrap()).unwrap();
            assert_eq!(xyz_bits(&exact), xyz_bits(&decoded));
        }
    };
}

python_fixture!(decode_v1_block, "v1_block", true);
python_fixture!(decode_v1_millimeter, "v1_1mm", true);
python_fixture!(decode_v1_centimeter, "v1_1cm", true);
python_fixture!(decode_v2_inferred_direction, "v2_inferred", true);
python_fixture!(decode_v2_stored_direction, "v2_stored", true);
python_fixture!(decode_exact_block, "block_exact", true);
python_fixture!(decode_millimeter_block, "block_1mm", false);
python_fixture!(decode_centimeter_block, "block_1cm", false);
python_fixture!(decode_exact_edited_block, "edited_block_exact", true);
python_fixture!(decode_millimeter_edited_block, "edited_block_1mm", true);
python_fixture!(decode_centimeter_edited_block, "edited_block_1cm", true);
python_fixture!(
    decode_exact_incomplete_block,
    "incomplete_block_exact",
    true
);
python_fixture!(
    decode_millimeter_incomplete_block,
    "incomplete_block_1mm",
    true
);
python_fixture!(
    decode_centimeter_incomplete_block,
    "incomplete_block_1cm",
    true
);
python_fixture!(decode_exact_signed_zero, "signed_zero_exact", true);
python_fixture!(decode_millimeter_signed_zero, "signed_zero_1mm", true);
python_fixture!(decode_centimeter_signed_zero, "signed_zero_1cm", true);
python_fixture!(decode_exact_ties, "ties_exact", true);
python_fixture!(decode_millimeter_ties, "ties_1mm", true);
python_fixture!(decode_centimeter_ties, "ties_1cm", true);
python_fixture!(decode_exact_adjacent_block, "adjacent_block_exact", true);
python_fixture!(
    decode_millimeter_adjacent_block,
    "adjacent_block_1mm",
    false
);
python_fixture!(
    decode_centimeter_adjacent_block,
    "adjacent_block_1cm",
    false
);
python_fixture!(decode_exact_nested_block, "nested_block_exact", true);
python_fixture!(decode_millimeter_nested_block, "nested_block_1mm", true);
python_fixture!(decode_centimeter_nested_block, "nested_block_1cm", true);
python_fixture!(decode_exact_first_block, "first_block_exact", true);
python_fixture!(decode_millimeter_first_block, "first_block_1mm", false);
python_fixture!(decode_centimeter_first_block, "first_block_1cm", false);
python_fixture!(decode_exact_large_book, "large_book_exact", true);
python_fixture!(decode_millimeter_large_book, "large_book_1mm", false);
python_fixture!(decode_centimeter_large_book, "large_book_1cm", false);

fn compress(raw: &[u8]) -> Vec<u8> {
    let mut encoder = ZlibEncoder::new(Vec::new(), Compression::best());
    encoder.write_all(raw).unwrap();
    encoder.finish().unwrap()
}

fn single_route(points: Vec<Point>) -> Snapshot {
    Snapshot {
        version: 1,
        kind: ShareKind::Play,
        plays: vec![Play {
            formation_name: "Unknown".into(),
            play_name: "".into(),
            routes: vec![Route { slot: 250, points }],
        }],
    }
}

#[test]
fn encode_snapshot_rounds_ties_to_even_like_python() {
    let source: Snapshot =
        serde_json::from_str(include_str!("fixtures/quickshare/ties_exact.json")).unwrap();
    for (precision, expected) in [
        (
            Precision::Millimeter,
            include_str!("fixtures/quickshare/ties_1mm.json"),
        ),
        (
            Precision::Centimeter,
            include_str!("fixtures/quickshare/ties_1cm.json"),
        ),
    ] {
        let restored = decode_share(&encode_snapshot(&source, precision).unwrap()).unwrap();
        assert_content(&restored, &serde_json::from_str(expected).unwrap(), true);
    }
}

#[test]
fn encode_snapshot_retains_hand_edited_and_incomplete_blocks_at_every_precision() {
    for source in [
        include_str!("fixtures/quickshare/edited_block_exact.json"),
        include_str!("fixtures/quickshare/incomplete_block_exact.json"),
    ] {
        let snapshot: Snapshot = serde_json::from_str(source).unwrap();
        for precision in [
            Precision::Exact,
            Precision::Millimeter,
            Precision::Centimeter,
        ] {
            let restored = decode_share(&encode_snapshot(&snapshot, precision).unwrap()).unwrap();
            assert_content(&restored, &snapshot, true);
        }
    }
}

#[test]
fn encode_snapshot_compresses_standard_blocks() {
    let source = include_bytes!("fixtures/quickshare/v1_block.gridironshare");
    let snapshot = decode_share(source).unwrap();
    for precision in [
        Precision::Exact,
        Precision::Millimeter,
        Precision::Centimeter,
    ] {
        assert!(encode_snapshot(&snapshot, precision).unwrap().len() < source.len() / 2);
    }
}

#[test]
fn encode_snapshot_keeps_compact_blocks_stable() {
    let source: Snapshot =
        serde_json::from_str(include_str!("fixtures/quickshare/block_exact.json")).unwrap();
    for precision in [Precision::Millimeter, Precision::Centimeter] {
        let encoded = encode_snapshot(&source, precision).unwrap();
        assert_eq!(
            encode_snapshot(&decode_share(&encoded).unwrap(), precision).unwrap(),
            encoded
        );
    }
}

#[test]
fn encode_snapshot_falls_back_to_exact_for_large_grid_coordinates() {
    let snapshot = single_route(vec![Point {
        x: 1e15,
        y: -1e15,
        z: 3.25,
    }]);
    for precision in [Precision::Millimeter, Precision::Centimeter] {
        assert_content(
            &decode_share(&encode_snapshot(&snapshot, precision).unwrap()).unwrap(),
            &snapshot,
            true,
        );
    }
}

#[test]
fn decode_share_rejects_truncation_trailing_streams_and_bytes() {
    let valid = include_bytes!("fixtures/quickshare/signed_zero_exact.gridironshare");
    let mut trailing = valid.to_vec();
    trailing.push(0);
    let doubled = [valid.as_slice(), valid.as_slice()].concat();
    for invalid in [
        &valid[..valid.len() - 1],
        trailing.as_slice(),
        doubled.as_slice(),
        b"not compressed",
    ] {
        assert_eq!(decode_share(invalid).unwrap_err().code, "invalid_share");
    }
}

#[test]
fn decode_share_rejects_oversized_compressed_and_inflated_data() {
    let oversized = vec![0; MAX_SHARE_BYTES + 1];
    assert_eq!(
        decode_share(&oversized).unwrap_err().code,
        "share_too_large"
    );
    assert_eq!(
        decode_share(&compress(&oversized)).unwrap_err().code,
        "share_too_large"
    );
}

#[test]
fn decode_share_rejects_invalid_headers_counts_and_utf8() {
    for raw in [
        b"GQS\x03\x00".as_slice(),
        b"GQS\x01\x02",
        b"GQS\x01\x00\x00",
        b"GQS\x01\x00\x81\x00\x01F\x01\x00\x01P\x00",
        b"GQS\x01\x00\x01\x01\xff\x01\x00\x01P\x00",
        b"GQS\x01\x00\x01\x01F\x00",
        b"GQS\x01\x00\x01\x01F\x01\x00\x01P\x01\x05\x00\xff\xff\x7f",
        b"GQS\x01\x00\x01\x01F\x01\x00\x01P\x00x",
    ] {
        assert_eq!(
            decode_share(&compress(raw)).unwrap_err().code,
            "invalid_share"
        );
    }
}

#[test]
fn decode_share_rejects_invalid_block_instructions() {
    let mut prefix = b"GQS\x02\x00\x01\x01F\x01\x00\x01P\x01\x05\x08\x02".to_vec();
    for value in [0.0f64, 0.0, 1.0, 0.0] {
        prefix.extend_from_slice(&value.to_le_bytes());
    }
    let mut nonunit = b"\x01\x01\x01".to_vec();
    nonunit.extend_from_slice(&2.0f64.to_le_bytes());
    nonunit.extend_from_slice(&0.0f64.to_le_bytes());
    for table in [
        b"\x00".as_slice(),
        b"\x01\x02\x00",
        b"\x01\x00\x00",
        b"\x01\x01\x03",
        b"\x01\x01\x02\x00\x00",
        &nonunit,
    ] {
        let raw = [prefix.as_slice(), table].concat();
        assert_eq!(
            decode_share(&compress(&raw)).unwrap_err().code,
            "invalid_share"
        );
    }
}

#[test]
fn encode_snapshot_rejects_nonfinite_and_unprojectable_coordinates() {
    for x in [f64::NAN, f64::INFINITY, -f64::INFINITY, f64::MAX] {
        let snapshot = single_route(vec![Point { x, y: 0.0, z: 0.0 }]);
        assert_eq!(
            encode_snapshot(&snapshot, Precision::Exact)
                .unwrap_err()
                .code,
            "invalid_share"
        );
    }
}
