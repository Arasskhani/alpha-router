import { describe, expect, it } from "vitest";
import {
  groundingPolicyFromToggles,
  groundingTogglesFromPolicy,
  assignableProjectRoles,
  isPrimaryOwnerRole,
  isProjectOwnerRole,
  MAX_PROJECT_RESOURCE_UPLOAD_FILES,
  needsPublicTypedConfirm,
  projectResourceKnowledgeStatus,
  projectResourceTooManyFilesMessage,
  projectResourceUserStatus,
  projectRoleLabel,
  queueProjectMediaForChat,
  type ProjectMediaItem,
} from "./projectsApi";

const item: ProjectMediaItem = {
  id: 7,
  projectId: "proj-abc",
  kind: "image",
  mimeType: "image/png",
  fileName: "shot.png",
  sizeBytes: 1200,
  storagePath: "projects/proj-abc/media/abc",
  url: "/api/projects/proj-abc/media/7/download",
};

describe("groundingPolicyFromToggles", () => {
  it("serializes toggle flags into grounding_policy keys", () => {
    expect(
      groundingPolicyFromToggles({ useProjectResources: false, useGrantedMemory: true }),
    ).toEqual({
      useProjectResources: false,
      useGrantedMemory: true,
    });
  });

  it("round-trips with groundingTogglesFromPolicy defaults", () => {
    const policy = groundingPolicyFromToggles({
      useProjectResources: true,
      useGrantedMemory: false,
    });
    expect(groundingTogglesFromPolicy(policy)).toEqual({
      useProjectResources: true,
      useGrantedMemory: false,
    });
    expect(groundingTogglesFromPolicy(undefined)).toEqual({
      useProjectResources: true,
      useGrantedMemory: true,
    });
  });
});

describe("project role helpers", () => {
  it("treats Primary Owner and Owner as management roles", () => {
    expect(isProjectOwnerRole("primary_owner")).toBe(true);
    expect(isProjectOwnerRole("owner")).toBe(true);
    expect(isProjectOwnerRole("contributor")).toBe(false);
    expect(isPrimaryOwnerRole("primary_owner")).toBe(true);
    expect(isPrimaryOwnerRole("owner")).toBe(false);
  });

  it("labels Primary Owner distinctly and limits assignable roles", () => {
    expect(projectRoleLabel("primary_owner")).toBe("Primary Owner");
    expect(assignableProjectRoles("primary_owner")).toEqual(["owner", "contributor", "viewer"]);
    expect(assignableProjectRoles("owner")).toEqual(["contributor", "viewer"]);
    expect(assignableProjectRoles("contributor")).toEqual([]);
  });
});

describe("needsPublicTypedConfirm", () => {
  it("requires typed PUBLIC only when switching to public", () => {
    expect(needsPublicTypedConfirm("private", "public")).toBe(true);
    expect(needsPublicTypedConfirm("public", "public")).toBe(false);
    expect(needsPublicTypedConfirm("public", "private")).toBe(false);
    expect(needsPublicTypedConfirm("private", "private")).toBe(false);
  });
});

describe("queueProjectMediaForChat", () => {
  it("includes projectId in the use-in-chat payload", () => {
    const payload = queueProjectMediaForChat(item, "proj-abc");
    expect(payload.projectId).toBe("proj-abc");
    expect(payload.mediaId).toBe(7);
    expect(payload.url).toBe("/api/projects/proj-abc/media/7/download");
    expect(payload.fileName).toBe("shot.png");
    expect(payload.mimeType).toBe("image/png");
  });
});

describe("project resource upload limits", () => {
  it("uses the same 20-file cap and message as Knowledge Bases", () => {
    expect(MAX_PROJECT_RESOURCE_UPLOAD_FILES).toBe(20);
    expect(projectResourceTooManyFilesMessage(21)).toBe(
      "You can upload at most 20 files at a time. You selected 21. Please choose 20 or fewer and try again.",
    );
  });

  it("prefers Knowledge version status for display", () => {
    expect(
      projectResourceKnowledgeStatus({
        id: "r1",
        projectId: "p1",
        documentId: "d1",
        title: "Doc",
        status: "processing",
        versionStatus: "review",
        documentStatus: "active",
      }),
    ).toBe("review");
  });

  it("shows Waiting for Admin Approval until the resource is Published", () => {
    const base = {
      id: "r1",
      projectId: "p1",
      documentId: "d1",
      title: "Doc",
      status: "processing" as const,
    };
    expect(projectResourceUserStatus({ ...base, versionStatus: "quarantined" })).toBe(
      "Waiting for Admin Approval",
    );
    expect(projectResourceUserStatus({ ...base, versionStatus: "processing" })).toBe(
      "Waiting for Admin Approval",
    );
    expect(projectResourceUserStatus({ ...base, versionStatus: "review" })).toBe(
      "Waiting for Admin Approval",
    );
    expect(projectResourceUserStatus({ ...base, status: "active", versionStatus: "published" })).toBe(
      "Published",
    );
    expect(projectResourceUserStatus({ ...base, status: "failed", versionStatus: "failed" })).toBe(
      "Failed",
    );
  });
});
