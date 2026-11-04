import * as engine from "./engine";
import type { DocumentView, EditCommand, Play, Point } from "./types";

export interface Draft {
  slot: number;
  points: Point[];
}
export interface PlaybookTab {
  id: string;
  name: string;
  document: string;
  savedDocument: string;
  view: DocumentView;
  selection: number[];
  selectedRoute: number | null;
  draft: Draft | null;
  search: string;
}
interface SavedTab extends Omit<PlaybookTab, "view"> {}
interface SavedWorkspace {
  version: 1;
  tabs: SavedTab[];
  activeId: string | null;
}
interface Change {
  tab: SavedTab;
  before: string;
  after: string;
}
interface Transaction {
  changes: Change[];
}

export interface WorkspaceEngine {
  inspectDocument(document: string): Promise<DocumentView>;
  applyEdit(document: string, command: EditCommand): Promise<string>;
  transferPlays(
    source: string,
    target: string,
    indices: number[],
    insertion: number,
    mode: "copy" | "move"
  ): Promise<{ source: string; target: string }>;
}

function savedTab(tab: PlaybookTab): SavedTab {
  return {
    id: tab.id,
    name: tab.name,
    document: tab.document,
    savedDocument: tab.savedDocument,
    selection: [...tab.selection],
    selectedRoute: tab.selectedRoute,
    draft: tab.draft ? { slot: tab.draft.slot, points: tab.draft.points.map((point) => ({ ...point })) } : null,
    search: tab.search,
  };
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function point(value: unknown): value is Point {
  return (
    record(value) &&
    typeof value.x === "number" &&
    Number.isFinite(value.x) &&
    typeof value.y === "number" &&
    Number.isFinite(value.y) &&
    typeof value.z === "number" &&
    Number.isFinite(value.z)
  );
}
function saved(value: unknown): value is SavedTab {
  return (
    record(value) &&
    typeof value.id === "string" &&
    value.id.length > 0 &&
    typeof value.name === "string" &&
    typeof value.document === "string" &&
    typeof value.savedDocument === "string" &&
    typeof value.search === "string" &&
    Array.isArray(value.selection) &&
    value.selection.every((index) => Number.isSafeInteger(index) && index >= 0) &&
    (value.selectedRoute === null || (Number.isSafeInteger(value.selectedRoute) && Number(value.selectedRoute) >= 0)) &&
    (value.draft === null ||
      (record(value.draft) &&
        Number.isInteger(value.draft.slot) &&
        Number(value.draft.slot) >= 0 &&
        Number(value.draft.slot) <= 255 &&
        Array.isArray(value.draft.points) &&
        value.draft.points.every(point)))
  );
}

export class Workspace {
  tabs: PlaybookTab[] = [];
  activeId: string | null = null;
  private past: Transaction[] = [];
  private future: Transaction[] = [];

  constructor(private readonly api: WorkspaceEngine = engine) {}

  get active(): PlaybookTab | undefined {
    return this.tabs.find((tab) => tab.id === this.activeId);
  }
  get play(): Play | undefined {
    return this.active?.view.plays[this.active.selection[0] ?? -1];
  }
  get canUndo(): boolean {
    return this.past.length > 0;
  }
  get canRedo(): boolean {
    return this.future.length > 0;
  }

  async open(document: string, name: string): Promise<PlaybookTab> {
    const view = await this.api.inspectDocument(document);
    const tab: PlaybookTab = {
      id: crypto.randomUUID(),
      name,
      document,
      savedDocument: document,
      view,
      selection: view.plays.length ? [0] : [],
      selectedRoute: null,
      draft: null,
      search: "",
    };
    this.tabs.push(tab);
    this.activeId = tab.id;
    return tab;
  }

  activate(id: string): void {
    if (!this.tabs.some((tab) => tab.id === id)) throw new Error("This playbook is no longer open.");
    this.activeId = id;
  }

  close(id: string): void {
    const index = this.tabs.findIndex((tab) => tab.id === id);
    if (index < 0) return;
    this.tabs.splice(index, 1);
    if (this.activeId === id) this.activeId = this.tabs[Math.min(index, this.tabs.length - 1)]?.id ?? null;
  }

  select(index: number, extend = false, toggle = false): void {
    const tab = this.active;
    if (!tab || !tab.view.plays[index]) return;
    if (extend && tab.selection.length) {
      const anchor = tab.selection[0]!;
      tab.selection = Array.from(
        { length: Math.abs(index - anchor) + 1 },
        (_, offset) => Math.min(index, anchor) + offset
      );
    } else if (toggle) {
      tab.selection = tab.selection.includes(index)
        ? tab.selection.filter((value) => value !== index)
        : [...tab.selection, index].sort((a, b) => a - b);
    } else {
      tab.selection = [index];
    }
    tab.selectedRoute = null;
    tab.draft = null;
  }

  async edit(command: EditCommand, selection?: number[]): Promise<void> {
    const tab = this.active;
    if (!tab) throw new Error("Open a playbook first.");
    const document = await this.api.applyEdit(tab.document, command);
    await this.commit([{ tab, document }]);
    if (selection) tab.selection = selection;
    this.normalize(tab);
  }

  async replace(id: string, document: string, selection?: number[]): Promise<void> {
    const tab = this.tabs.find((candidate) => candidate.id === id);
    if (!tab) throw new Error("This playbook is no longer open.");
    this.requireFinishedDraft(tab);
    await this.commit([{ tab, document }]);
    if (selection) tab.selection = selection;
    this.normalize(tab);
  }

  async transfer(
    sourceId: string,
    targetId: string,
    indices: number[],
    insertion: number,
    mode: "copy" | "move"
  ): Promise<void> {
    const source = this.tabs.find((tab) => tab.id === sourceId);
    const target = this.tabs.find((tab) => tab.id === targetId);
    if (!source || !target) throw new Error("A selected playbook is no longer open.");
    this.requireFinishedDraft(source);
    this.requireFinishedDraft(target);
    const ordered = [...indices].sort((a, b) => a - b);
    if (source === target) {
      const document =
        mode === "copy"
          ? (await this.api.transferPlays(source.document, source.document, ordered, insertion, "copy")).target
          : await this.api.applyEdit(source.document, { type: "reorder_plays", indices: ordered, insertion });
      await this.commit([{ tab: source, document }]);
      const start = mode === "copy" ? insertion : insertion - ordered.filter((index) => index < insertion).length;
      target.selection = ordered.map((_, index) => start + index);
    } else {
      const result = await this.api.transferPlays(source.document, target.document, ordered, insertion, mode);
      await this.commit([
        { tab: source, document: result.source },
        { tab: target, document: result.target },
      ]);
      target.selection = ordered.map((_, index) => insertion + index);
    }
    this.activeId = target.id;
    target.selectedRoute = null;
    target.draft = null;
  }

  private async commit(updates: { tab: PlaybookTab; document: string }[]): Promise<void> {
    const changed = updates.filter((update) => update.document !== update.tab.document);
    if (!changed.length) return;
    const views = await Promise.all(changed.map((update) => this.api.inspectDocument(update.document)));
    this.past.push({
      changes: changed.map(({ tab, document }) => ({ tab: savedTab(tab), before: tab.document, after: document })),
    });
    if (this.past.length > 100) this.past.shift();
    this.future = [];
    changed.forEach(({ tab, document }, index) => {
      tab.document = document;
      tab.view = views[index]!;
      this.normalize(tab);
    });
  }

  private normalize(tab: PlaybookTab): void {
    tab.selection = tab.selection.filter((index) => index >= 0 && index < tab.view.plays.length);
    if (!tab.selection.length && tab.view.plays.length) tab.selection = [0];
    const play = tab.view.plays[tab.selection[0] ?? -1];
    if (tab.selectedRoute !== null && !play?.routes[tab.selectedRoute]) tab.selectedRoute = null;
  }

  private requireFinishedDraft(tab: PlaybookTab): void {
    if (tab.draft) throw new Error(`Finish or cancel the route in ${tab.name} first.`);
  }

  async undo(): Promise<void> {
    await this.travel(this.past, this.future, "before");
  }
  async redo(): Promise<void> {
    await this.travel(this.future, this.past, "after");
  }

  private async travel(from: Transaction[], to: Transaction[], direction: "before" | "after"): Promise<void> {
    const transaction = from.at(-1);
    if (!transaction) return;
    for (const change of transaction.changes) {
      const tab = this.tabs.find((candidate) => candidate.id === change.tab.id);
      if (tab) this.requireFinishedDraft(tab);
    }
    const views = await Promise.all(transaction.changes.map((change) => this.api.inspectDocument(change[direction])));
    from.pop();
    to.push(transaction);
    transaction.changes.forEach((change, index) => {
      let tab = this.tabs.find((candidate) => candidate.id === change.tab.id);
      if (!tab) {
        tab = { ...change.tab, selection: [...change.tab.selection], view: views[index]! };
        this.tabs.push(tab);
      }
      tab.document = change[direction];
      tab.view = views[index]!;
      tab.draft = null;
      tab.selectedRoute = null;
      this.normalize(tab);
    });
    if (!this.active) this.activeId = transaction.changes[0]?.tab.id ?? null;
  }

  markSaved(id: string, document: string): void {
    const tab = this.tabs.find((candidate) => candidate.id === id);
    if (tab) tab.savedDocument = document;
  }

  serialize(): string {
    const snapshot: SavedWorkspace = { version: 1, tabs: this.tabs.map(savedTab), activeId: this.activeId };
    return JSON.stringify(snapshot);
  }

  async restore(data: string): Promise<void> {
    const value: unknown = JSON.parse(data);
    if (
      !record(value) ||
      value.version !== 1 ||
      !Array.isArray(value.tabs) ||
      !value.tabs.every(saved) ||
      (value.activeId !== null && typeof value.activeId !== "string")
    )
      throw new Error("The saved workspace is not supported.");
    const tabs = value.tabs;
    if (
      new Set(tabs.map((tab) => tab.id)).size !== tabs.length ||
      (tabs.length ? !tabs.some((tab) => tab.id === value.activeId) : value.activeId !== null)
    ) {
      throw new Error("The saved workspace has invalid tab identities.");
    }
    const views = await Promise.all(
      tabs.map(async (tab) => {
        await this.api.inspectDocument(tab.savedDocument);
        return this.api.inspectDocument(tab.document);
      })
    );
    this.tabs = tabs.map((tab, index) => ({ ...tab, view: views[index]! }));
    this.activeId = value.activeId;
    this.tabs.forEach((tab) => this.normalize(tab));
    this.past = [];
    this.future = [];
  }
}
