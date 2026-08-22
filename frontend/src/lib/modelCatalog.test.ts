import { describe, expect, it } from "vitest";
import {
  filterCatalogModels,
  isNewlyListedModel,
  newWindowCounts,
  type CatalogModel,
} from "./modelCatalog";

function model(partial: Partial<CatalogModel> & Pick<CatalogModel, "id" | "external_id">): CatalogModel {
  return {
    enabled: true,
    input_cost_per_1k: null,
    output_cost_per_1k: null,
    total_cost_per_1k: 0,
    ...partial,
  };
}

const NOW = Date.parse("2026-08-22T12:00:00.000Z");

describe("isNewlyListedModel", () => {
  it("rejects models without a first-seen time", () => {
    expect(isNewlyListedModel(model({ id: 1, external_id: "a" }), 7, NOW)).toBe(false);
    expect(isNewlyListedModel(model({ id: 2, external_id: "b", first_seen_at: null }), 7, NOW)).toBe(
      false,
    );
  });

  it("uses a rolling window from first_seen_at", () => {
    const recent = model({
      id: 3,
      external_id: "new",
      first_seen_at: "2026-08-21T12:00:00.000Z",
    });
    const older = model({
      id: 4,
      external_id: "old",
      first_seen_at: "2026-08-18T12:00:00.000Z",
    });
    expect(isNewlyListedModel(recent, 1, NOW)).toBe(true);
    expect(isNewlyListedModel(older, 1, NOW)).toBe(false);
    expect(isNewlyListedModel(older, 7, NOW)).toBe(true);
  });
});

describe("newWindowCounts", () => {
  it("counts each window independently and skips rows without first_seen_at", () => {
    const models = [
      model({ id: 1, external_id: "legacy" }),
      model({ id: 2, external_id: "1d", first_seen_at: "2026-08-22T06:00:00.000Z" }),
      model({ id: 3, external_id: "3d", first_seen_at: "2026-08-20T12:00:00.000Z" }),
      model({ id: 4, external_id: "30d", first_seen_at: "2026-08-01T12:00:00.000Z" }),
    ];
    expect(newWindowCounts(models, NOW)).toEqual({
      1: 1,
      3: 2,
      7: 2,
      14: 2,
      30: 3,
    });
  });
});

describe("filterCatalogModels new window", () => {
  it("ANDs the New filter with other catalog filters", () => {
    const models = [
      model({
        id: 1,
        external_id: "kept",
        enabled: true,
        access_type: "public",
        first_seen_at: "2026-08-21T12:00:00.000Z",
      }),
      model({
        id: 2,
        external_id: "off",
        enabled: false,
        first_seen_at: "2026-08-21T12:00:00.000Z",
      }),
      model({
        id: 3,
        external_id: "old",
        first_seen_at: "2026-07-01T12:00:00.000Z",
      }),
    ];
    const filtered = filterCatalogModels(models, "", null, "on", "public", 3, NOW);
    expect(filtered.map((m) => m.external_id)).toEqual(["kept"]);
  });
});
