export interface Point {
  x: number;
  y: number;
  z: number;
}
export interface Route {
  slot: number;
  points: Point[];
  yards?: number;
  ends_with_block?: boolean;
}
export interface Play {
  formation_name: string;
  play_name: string;
  routes: Route[];
}
export interface DocumentView {
  plays: Play[];
}
export interface Position {
  slot: number;
  label: string;
  x: number;
  y: number;
}
export interface Formation {
  name: string;
  positions: Position[];
}
export type ShareKind = "play" | "playbook";
export type SharePrecision = "exact" | "1mm" | "1cm";
export interface ShareView extends DocumentView {
  version: 1;
  kind: ShareKind;
}
export interface ImportedShare {
  kind: ShareKind;
  document: string;
}
export interface TransferredPlays {
  source: string;
  target: string;
}
export type EditCommand =
  | { type: "create_play"; formation_name: string; play_name: string }
  | { type: "duplicate_play" | "rename_play"; play_index: number; play_name: string }
  | { type: "change_formation"; play_index: number; formation_name: string }
  | { type: "delete_plays"; indices: number[] }
  | { type: "reorder_plays"; indices: number[]; insertion: number }
  | { type: "add_route"; play_index: number; slot: number; points: Point[] }
  | {
      type: "move_point" | "insert_point";
      play_index: number;
      route_index: number;
      point_index: number;
      x: number;
      y: number;
    }
  | { type: "delete_point" | "add_block"; play_index: number; route_index: number; point_index: number }
  | { type: "delete_route"; play_index: number; route_index: number }
  | { type: "clear_routes" | "flip_play"; play_index: number };
