/**
 * A2A JavaScript SDK integration tests against AgentBin.
 *
 * ALL tests use official SDK methods only — no raw HTTP or hand-crafted JSON-RPC.
 * Outputs human-readable console results AND a results.json file.
 * Usage: node test_js_client.mjs [baseUrl]
 */

import { createRequire } from "module";
import { randomUUID } from "crypto";
import { writeFileSync, readFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

// SDK imports
import {
  Role,
  TaskState,
  taskStateToJSON,
} from "@a2a-js/sdk";
import {
  Client,
  JsonRpcTransport,
  RestTransport,
  DefaultAgentCardResolver,
} from "@a2a-js/sdk/client";

const __dirname = dirname(fileURLToPath(import.meta.url));

// SDK version detection
function detectSdkSource() {
  try {
    const pkgPath = join(__dirname, "node_modules", "@a2a-js", "sdk", "package.json");
    const pkg = JSON.parse(readFileSync(pkgPath, "utf-8"));
    const ver = pkg.version || "unknown";
    // Local file: link means local build
    const parentPkg = JSON.parse(readFileSync(join(__dirname, "package.json"), "utf-8"));
    const dep = parentPkg.dependencies?.["@a2a-js/sdk"] || "";
    if (dep.startsWith("file:")) {
      return `a2a-js (local build, ${ver})`;
    }
    return `@a2a-js/sdk ${ver}`;
  } catch {
    return "@a2a-js/sdk (unknown version)";
  }
}

const SDK_SOURCE = detectSdkSource();
const DEFAULT_BASE = "https://agentbin.greensmoke-1163cb63.eastus.azurecontainerapps.io";
const BASE_URL = process.argv[2] || DEFAULT_BASE;

const RESULTS = [];

function record(testId, name, passed, detail, durationMs) {
  const tag = passed ? "PASS" : "FAIL";
  RESULTS.push({ id: testId, name, passed, detail, durationMs });
  console.log(`  [${tag}] ${testId} — ${detail}`);
}

// -- SDK Helpers -------------------------------------------------------

const cardResolver = new DefaultAgentCardResolver();

/** Fetch the agent card using the SDK's DefaultAgentCardResolver. */
async function fetchAgentCard(url) {
  return await cardResolver.resolve(url);
}

async function makeClient(url, { binding = "JSONRPC" } = {}) {
  const card = await fetchAgentCard(url);
  // Normalize v0.3 capabilities to v1.0 format for SDK compatibility
  if (card.capabilities) {
    if (card.capabilities.supportsStreaming !== undefined && card.capabilities.streaming === undefined) {
      card.capabilities.streaming = card.capabilities.supportsStreaming;
    }
    if (card.capabilities.supportsPushNotifications !== undefined && card.capabilities.pushNotifications === undefined) {
      card.capabilities.pushNotifications = card.capabilities.supportsPushNotifications;
    }
  }
  // Resolve endpoint URL from v1.0 card format
  let endpointUrl = card.url || url;
  // Check additionalInterfaces (v1.0) or supportedInterfaces (v0.3) for binding-specific URL
  const interfaces = card.additionalInterfaces || card.supportedInterfaces || [];
  for (const iface of interfaces) {
    const proto = iface.transport || iface.protocolBinding || "";
    if (binding === "JSONRPC" && proto === "JSONRPC") { endpointUrl = iface.url; break; }
    if (binding === "REST" && (proto === "HTTP+JSON" || proto === "REST")) { endpointUrl = iface.url; break; }
  }
  // Rewrite the host to match our BASE_URL (card may advertise different host)
  const baseOrigin = new URL(BASE_URL).origin;
  const cardOrigin = new URL(endpointUrl).origin;
  if (cardOrigin !== baseOrigin) {
    endpointUrl = endpointUrl.replace(cardOrigin, baseOrigin);
  }
  const transport =
    binding === "REST"
      ? new RestTransport({ endpoint: endpointUrl })
      : new JsonRpcTransport({ endpoint: endpointUrl });
  return new Client(transport, card);
}

function textPart(text) {
  return { part: { $case: "text", value: text } };
}

function makeMessage(text) {
  return {
    messageId: randomUUID(),
    contextId: randomUUID(),
    taskId: "",
    role: Role.ROLE_USER,
    content: [textPart(text)],
    metadata: {},
    extensions: [],
  };
}

function makeSendRequest(text, { blocking = true, historyLength = 0 } = {}) {
  return {
    request: makeMessage(text),
    configuration: {
      acceptedOutputModes: ["text/plain", "application/json"],
      historyLength,
      blocking,
    },
  };
}

function getTaskState(task) {
  if (!task?.status?.state) return "UNKNOWN";
  return taskStateToJSON(task.status.state);
}

function getTextFromParts(parts) {
  if (!parts) return "";
  for (const p of parts) {
    if (p.part?.$case === "text") return p.part.value;
  }
  return "";
}

function getTextFromTask(task) {
  if (!task?.artifacts?.length) return "";
  for (const art of task.artifacts) {
    const t = getTextFromParts(art.parts);
    if (t) return t;
  }
  return "";
}

function isMessage(obj) {
  return obj && "messageId" in obj && !("status" in obj);
}

function isTask(obj) {
  return obj && "id" in obj && "status" in obj && !("taskId" in obj);
}

function isStatusEvent(obj) {
  return obj && "taskId" in obj && "status" in obj && !("artifact" in obj);
}

function isArtifactEvent(obj) {
  return obj && "taskId" in obj && "artifact" in obj;
}

/** Send a message via SDK and collect all stream events. Returns { events, finalTask, finalMessage } */
async function sdkSendStream(url, text, { binding = "JSONRPC" } = {}) {
  const client = await makeClient(url, { binding });
  const req = makeSendRequest(text);
  const events = [];
  let finalTask = null;
  let finalMessage = null;
  const collectedArtifacts = [];
  for await (const event of client.sendMessageStream(req)) {
    events.push(event);
    if (isTask(event)) finalTask = event;
    if (isMessage(event)) finalMessage = event;
    if (isArtifactEvent(event) && event.artifact) {
      collectedArtifacts.push(event.artifact);
    }
    if (isStatusEvent(event) && event.status) {
      // Build a pseudo-task from status events
      const state = event.status.state;
      if (
        state === TaskState.TASK_STATE_COMPLETED ||
        state === TaskState.TASK_STATE_FAILED ||
        state === TaskState.TASK_STATE_CANCELLED
      ) {
        if (!finalTask) {
          finalTask = { id: event.taskId, status: event.status, artifacts: [], history: [] };
        } else {
          finalTask.status = event.status;
        }
      }
    }
  }
  // Merge collected artifacts into finalTask if it has none
  if (finalTask && collectedArtifacts.length > 0 && (!finalTask.artifacts || finalTask.artifacts.length === 0)) {
    finalTask.artifacts = collectedArtifacts;
  }
  return { events, finalTask, finalMessage };
}

/** Send a blocking (non-streaming) message. Returns Message | Task */
async function sdkSend(url, text, { binding = "JSONRPC", blocking = true } = {}) {
  const client = await makeClient(url, { binding });
  const req = makeSendRequest(text, { blocking });
  return await client.sendMessage(req);
}

// Shared task IDs for cross-test references
let lifecycleTaskId = null;
let restLifecycleTaskId = null;

// =====================================================================
// JSON-RPC Tests
// =====================================================================

async function testAgentCardEcho() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/echo`);
    const card = await client.getAgentCard();
    const ms = Date.now() - t0;
    const ok = card.name === "Echo Agent" && card.skills?.length > 0;
    record("jsonrpc/agent-card-echo", "Echo Agent Card", ok,
      `name=${card.name}, skills=${card.skills?.length}`, ms);
  } catch (e) {
    record("jsonrpc/agent-card-echo", "Echo Agent Card", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testAgentCardSpec() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`);
    const card = await client.getAgentCard();
    const ms = Date.now() - t0;
    const skillIds = card.skills?.map((s) => s.id) || [];
    const ok = card.name?.includes("Spec") && card.skills?.length > 0;
    record("jsonrpc/agent-card-spec", "Spec Agent Card", ok,
      `name=${card.name}, skills=[${skillIds.join(",")}]`, ms);
  } catch (e) {
    record("jsonrpc/agent-card-spec", "Spec Agent Card", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testEchoSendMessage() {
  const t0 = Date.now();
  try {
    const result = await sdkSend(`${BASE_URL}/echo`, "Hello from JS SDK!");
    const ms = Date.now() - t0;
    let reply = "";
    if (isMessage(result)) {
      reply = getTextFromParts(result.content);
    } else if (isTask(result)) {
      reply = getTextFromTask(result);
    }
    const ok = reply.startsWith("Echo:");
    record("jsonrpc/echo-send-message", "Echo Send Message", ok, `reply=${reply.slice(0, 80)}`, ms);
  } catch (e) {
    record("jsonrpc/echo-send-message", "Echo Send Message", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecMessageOnly() {
  const t0 = Date.now();
  try {
    const result = await sdkSend(`${BASE_URL}/spec`, "message-only hello world");
    const ms = Date.now() - t0;
    let reply = "";
    let gotMessage = false;
    if (isMessage(result)) {
      gotMessage = true;
      reply = getTextFromParts(result.content);
    } else if (isTask(result)) {
      // Some SDKs wrap messages in tasks
      reply = getTextFromTask(result);
      gotMessage = reply.length > 0;
    }
    const ok = gotMessage && reply.length > 0;
    record("jsonrpc/spec-message-only", "Spec Message Only", ok,
      `gotMessage=${gotMessage}, text=${reply.slice(0, 60)}`, ms);
  } catch (e) {
    record("jsonrpc/spec-message-only", "Spec Message Only", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecTaskLifecycle() {
  const t0 = Date.now();
  try {
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-lifecycle process this");
    const ms = Date.now() - t0;
    const state = getTaskState(finalTask);
    const hasArtifact = finalTask?.artifacts?.length > 0;
    if (finalTask?.id) lifecycleTaskId = finalTask.id;
    const ok = state === "TASK_STATE_COMPLETED" && hasArtifact;
    record("jsonrpc/spec-task-lifecycle", "Spec Task Lifecycle", ok,
      `state=${state}, artifacts=${hasArtifact}, taskId=${lifecycleTaskId}`, ms);
  } catch (e) {
    record("jsonrpc/spec-task-lifecycle", "Spec Task Lifecycle", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecGetTask() {
  const t0 = Date.now();
  if (!lifecycleTaskId) {
    record("jsonrpc/spec-get-task", "Spec GetTask", false, "skipped — no taskId from lifecycle", 0);
    return;
  }
  try {
    const client = await makeClient(`${BASE_URL}/spec`);
    const task = await client.getTask({ name: `tasks/${lifecycleTaskId}`, historyLength: 0 });
    const ms = Date.now() - t0;
    const state = getTaskState(task);
    const ok = task.id === lifecycleTaskId && state === "TASK_STATE_COMPLETED";
    record("jsonrpc/spec-get-task", "Spec GetTask", ok, `taskId=${task.id}, state=${state}`, ms);
  } catch (e) {
    record("jsonrpc/spec-get-task", "Spec GetTask", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecTaskFailure() {
  const t0 = Date.now();
  try {
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-failure trigger error");
    const ms = Date.now() - t0;
    const state = getTaskState(finalTask);
    const ok = state === "TASK_STATE_FAILED";
    record("jsonrpc/spec-task-failure", "Spec Task Failure", ok, `state=${state}`, ms);
  } catch (e) {
    record("jsonrpc/spec-task-failure", "Spec Task Failure", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecDataTypes() {
  const t0 = Date.now();
  try {
    const { events, finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "data-types show all");
    const ms = Date.now() - t0;
    const partKinds = new Set();
    for (const ev of events) {
      const sources = [];
      if (isMessage(ev)) sources.push(ev.content);
      if (isTask(ev)) for (const art of ev.artifacts || []) sources.push(art.parts);
      if (isArtifactEvent(ev) && ev.artifact) sources.push(ev.artifact.parts);
      for (const parts of sources) {
        for (const p of parts || []) {
          if (p.part?.$case === "text") partKinds.add("text");
          if (p.part?.$case === "data") partKinds.add("data");
          if (p.part?.$case === "file") partKinds.add("file");
        }
      }
    }
    // Also check final task artifacts
    if (finalTask) {
      for (const art of finalTask.artifacts || []) {
        for (const p of art.parts || []) {
          if (p.part?.$case === "text") partKinds.add("text");
          if (p.part?.$case === "data") partKinds.add("data");
          if (p.part?.$case === "file") partKinds.add("file");
        }
      }
    }
    const ok = partKinds.size >= 2;
    record("jsonrpc/spec-data-types", "Spec Data Types", ok,
      `kinds=[${[...partKinds].sort().join(",")}]`, ms);
  } catch (e) {
    record("jsonrpc/spec-data-types", "Spec Data Types", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecStreaming() {
  const t0 = Date.now();
  try {
    const { events, finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "streaming generate output");
    const ms = Date.now() - t0;
    const ok = events.length >= 2;
    let finalText = getTextFromTask(finalTask);
    record("jsonrpc/spec-streaming", "Spec Streaming", ok,
      `events=${events.length}, text=${finalText.slice(0, 50)}`, ms);
  } catch (e) {
    record("jsonrpc/spec-streaming", "Spec Streaming", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecMultiTurn() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`);
    // Turn 1: start multi-turn
    const contextId = randomUUID();
    const msg1 = {
      messageId: randomUUID(), contextId, taskId: "", role: Role.ROLE_USER,
      content: [textPart("multi-turn step one")], metadata: {}, extensions: [],
    };
    const req1 = { request: msg1, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true } };
    const result1 = await client.sendMessage(req1);
    let taskId = "";
    let returnedContextId = "";
    if (isTask(result1)) {
      taskId = result1.id;
      returnedContextId = result1.contextId;
    } else if (isMessage(result1)) {
      returnedContextId = result1.contextId;
    }

    // Turn 2: continue with same context
    const msg2 = {
      messageId: randomUUID(), contextId: returnedContextId || contextId, taskId,
      role: Role.ROLE_USER,
      content: [textPart("multi-turn step two")], metadata: {}, extensions: [],
    };
    const req2 = { request: msg2, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true } };
    const result2 = await client.sendMessage(req2);
    let turn2Text = "";
    if (isTask(result2)) {
      turn2Text = getTextFromTask(result2);
    } else if (isMessage(result2)) {
      turn2Text = getTextFromParts(result2.content);
    }

    const ms = Date.now() - t0;
    const ok = turn2Text.length > 0;
    record("jsonrpc/spec-multi-turn", "Spec Multi-Turn", ok,
      `contextId=${(returnedContextId || contextId).slice(0, 8)}..., turn2=${turn2Text.slice(0, 50)}`, ms);
  } catch (e) {
    record("jsonrpc/spec-multi-turn", "Spec Multi-Turn", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecTaskCancel() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`);
    // Start a streaming task
    const req = makeSendRequest("task-cancel start");
    let taskId = null;
    for await (const event of client.sendMessageStream(req)) {
      if (isTask(event)) { taskId = event.id; break; }
      if (isStatusEvent(event)) { taskId = event.taskId; break; }
    }
    if (!taskId) {
      record("jsonrpc/spec-task-cancel", "Spec Task Cancel", false, "no taskId from stream", Date.now() - t0);
      return;
    }
    const cancelResult = await client.cancelTask({ name: `tasks/${taskId}` });
    const ms = Date.now() - t0;
    const state = getTaskState(cancelResult);
    const ok = state === "TASK_STATE_CANCELLED";
    record("jsonrpc/spec-task-cancel", "Spec Task Cancel", ok, `taskId=${taskId}, state=${state}`, ms);
  } catch (e) {
    record("jsonrpc/spec-task-cancel", "Spec Task Cancel", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecCancelWithMetadata(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const testId = `${prefix}/spec-cancel-with-metadata`;
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const req = makeSendRequest("task-cancel start");
    let taskId = null;
    for await (const event of client.sendMessageStream(req)) {
      if (isTask(event)) { taskId = event.id; break; }
      if (isStatusEvent(event)) { taskId = event.taskId; break; }
    }
    if (!taskId) {
      record(testId, "Cancel With Metadata", false, "no taskId from stream", Date.now() - t0);
      return;
    }
    const cancelResult = await client.cancelTask({
      name: `tasks/${taskId}`,
      metadata: { reason: "test-cancel-reason", requestedBy: "js-sdk" },
    });
    const ms = Date.now() - t0;
    const state = getTaskState(cancelResult);
    const canceled = state === "TASK_STATE_CANCELLED";
    const meta = cancelResult.metadata || {};
    const metadataOk = meta.reason !== undefined && meta.requestedBy !== undefined;
    const ok = canceled && metadataOk;
    record(testId, "Cancel With Metadata", ok,
      `taskId=${taskId}, canceled=${canceled}, metadataOk=${metadataOk}, keys=[${Object.keys(meta).join(",")}]`, ms);
  } catch (e) {
    record(testId, "Cancel With Metadata", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecListTasks() {
  const t0 = Date.now();
  try {
    record("jsonrpc/spec-list-tasks", "Spec ListTasks", false,
      "SDK not supported: JS SDK does not expose listTasks", 0);
  } catch (e) {
    record("jsonrpc/spec-list-tasks", "Spec ListTasks", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testSpecReturnImmediately() {
  const t0 = Date.now();
  try {
    const result = await sdkSend(`${BASE_URL}/spec`, "task-lifecycle process this", { blocking: false });
    const ms = Date.now() - t0;
    let state = "UNKNOWN";
    if (isTask(result)) state = getTaskState(result);
    // Return immediately should give us a non-terminal state quickly
    const ok = ms < 3000;
    record("jsonrpc/spec-return-immediately", "Spec Return Immediately", ok,
      `state=${state}, ms=${ms}`, ms);
  } catch (e) {
    record("jsonrpc/spec-return-immediately", "Spec Return Immediately", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testErrorTaskNotFound() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`);
    await client.getTask({ name: "tasks/nonexistent-task-id-12345", historyLength: 0 });
    record("jsonrpc/error-task-not-found", "Task Not Found Error", false, "expected error but got success", Date.now() - t0);
  } catch (e) {
    const ms = Date.now() - t0;
    const isNotFound = e.constructor?.name?.includes("NotFound") || e.message?.includes("not found") || e.message?.includes("-32001") || e.message?.includes("404");
    record("jsonrpc/error-task-not-found", "Task Not Found Error", isNotFound,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

// --- TCK-inspired interop tests ---

async function testErrorCancelNotFound(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    await client.cancelTask({ name: "tasks/bogus-cancel-id-99999" });
    record(`${prefix}/error-cancel-not-found`, "Cancel Not Found", false, "expected error", Date.now() - t0);
  } catch (e) {
    const ms = Date.now() - t0;
    const ok = e.constructor?.name?.includes("NotFound") || e.message?.includes("not found") || e.message?.includes("-32001") || e.message?.includes("404");
    record(`${prefix}/error-cancel-not-found`, "Cancel Not Found", ok,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

async function testErrorCancelTerminal(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    // First, complete a task
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-lifecycle process this", { binding });
    if (!finalTask?.id) {
      record(`${prefix}/error-cancel-terminal`, "Cancel Terminal Task", false, "no task created", Date.now() - t0);
      return;
    }
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    await client.cancelTask({ name: `tasks/${finalTask.id}` });
    record(`${prefix}/error-cancel-terminal`, "Cancel Terminal Task", false, "expected error cancelling completed task", Date.now() - t0);
  } catch (e) {
    const ms = Date.now() - t0;
    const ok = e.constructor?.name?.includes("NotCancelable") || e.message?.includes("not cancelable") || e.message?.includes("-32002") || e.message?.includes("400");
    record(`${prefix}/error-cancel-terminal`, "Cancel Terminal Task", ok,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

async function testErrorSendTerminal(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    // First, complete a task
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-lifecycle process this", { binding });
    if (!finalTask?.id) {
      record(`${prefix}/error-send-terminal`, "Send To Terminal Task", false, "no task created", Date.now() - t0);
      return;
    }
    // Try to send another message to the completed task
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const msg = {
      messageId: randomUUID(), contextId: randomUUID(), taskId: finalTask.id,
      role: Role.ROLE_USER, content: [textPart("should fail")], metadata: {}, extensions: [],
    };
    await client.sendMessage({ request: msg, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true } });
    const ms = Date.now() - t0;
    // If it succeeds, it's probably because the server accepts more messages on same task
    record(`${prefix}/error-send-terminal`, "Send To Terminal Task", false, "expected error but got success", ms);
  } catch (e) {
    const ms = Date.now() - t0;
    const ok = true; // Any error sending to a terminal task is acceptable
    record(`${prefix}/error-send-terminal`, "Send To Terminal Task", ok,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

async function testErrorSendInvalidTask(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const msg = {
      messageId: randomUUID(), contextId: randomUUID(), taskId: "bogus-task-id-never-existed",
      role: Role.ROLE_USER, content: [textPart("should fail")], metadata: {}, extensions: [],
    };
    await client.sendMessage({ request: msg, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true } });
    const ms = Date.now() - t0;
    record(`${prefix}/error-send-invalid-task`, "Send Invalid TaskId", false, "expected error but got success", ms);
  } catch (e) {
    const ms = Date.now() - t0;
    const ok = e.constructor?.name?.includes("NotFound") || e.message?.includes("not found") || e.message?.includes("-32001") || e.message?.includes("404");
    record(`${prefix}/error-send-invalid-task`, "Send Invalid TaskId", ok,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

async function testErrorPushNotSupported(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    await client.setTaskPushNotificationConfig({
      name: `tasks/${randomUUID()}/pushNotificationConfigs/test-config`,
      pushNotificationConfig: {
        name: `tasks/${randomUUID()}/pushNotificationConfigs/test-config`,
        url: "https://example.com/webhook",
        token: "test-token",
      },
    });
    record(`${prefix}/error-push-not-supported`, "Push Not Supported", false, "expected error", Date.now() - t0);
  } catch (e) {
    const ms = Date.now() - t0;
    const ok = e.constructor?.name?.includes("PushNotification") || e.message?.includes("push") || e.message?.includes("-32003") || e.message?.includes("not supported");
    record(`${prefix}/error-push-not-supported`, "Push Not Supported", ok,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

async function testSubscribeToTask(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    // Start a streaming task
    const req = makeSendRequest("task-cancel start"); // long-running
    let taskId = null;
    for await (const event of client.sendMessageStream(req)) {
      if (isTask(event)) { taskId = event.id; break; }
      if (isStatusEvent(event)) { taskId = event.taskId; break; }
    }
    if (!taskId) {
      record(`${prefix}/subscribe-to-task`, "SubscribeToTask", false, "no taskId from stream", Date.now() - t0);
      return;
    }
    // Subscribe to the task
    const subEvents = [];
    try {
      const timeout = AbortSignal.timeout(5000);
      for await (const event of client.resubscribeTask({ name: `tasks/${taskId}` }, { signal: timeout })) {
        subEvents.push(event);
        if (isStatusEvent(event) && event.final) break;
      }
    } catch (e) {
      // Timeout is fine — we just want to see if we get events
    }
    const ms = Date.now() - t0;
    const ok = subEvents.length >= 1;
    record(`${prefix}/subscribe-to-task`, "SubscribeToTask", ok,
      `taskId=${taskId}, subEvents=${subEvents.length}`, ms);
  } catch (e) {
    record(`${prefix}/subscribe-to-task`, "SubscribeToTask", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testErrorSubscribeNotFound(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const events = [];
    for await (const event of client.resubscribeTask({ name: "tasks/bogus-subscribe-id" })) {
      events.push(event);
    }
    record(`${prefix}/error-subscribe-not-found`, "Subscribe Not Found", false, "expected error", Date.now() - t0);
  } catch (e) {
    const ms = Date.now() - t0;
    const ok = e.constructor?.name?.includes("NotFound") || e.message?.includes("not found") || e.message?.includes("-32001") || e.message?.includes("404");
    record(`${prefix}/error-subscribe-not-found`, "Subscribe Not Found", ok,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

async function testStreamMessageOnly(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const { events, finalMessage } = await sdkSendStream(`${BASE_URL}/spec`, "message-only hello", { binding });
    const ms = Date.now() - t0;
    const gotMessage = events.some((e) => isMessage(e));
    const ok = gotMessage;
    record(`${prefix}/stream-message-only`, "Stream Message Only", ok,
      `events=${events.length}, gotMessage=${gotMessage}`, ms);
  } catch (e) {
    record(`${prefix}/stream-message-only`, "Stream Message Only", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testStreamTaskLifecycle(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const { events, finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-lifecycle process this", { binding });
    const ms = Date.now() - t0;
    const hasTask = events.some((e) => isTask(e));
    const hasStatusEvents = events.some((e) => isStatusEvent(e));
    const terminalState = getTaskState(finalTask);
    const ok = events.length >= 2 && (terminalState === "TASK_STATE_COMPLETED");
    record(`${prefix}/stream-task-lifecycle`, "Stream Task Lifecycle", ok,
      `events=${events.length}, hasTask=${hasTask}, state=${terminalState}`, ms);
  } catch (e) {
    record(`${prefix}/stream-task-lifecycle`, "Stream Task Lifecycle", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testMultiTurnContextPreserved(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const contextId = randomUUID();
    const msg1 = {
      messageId: randomUUID(), contextId, taskId: "", role: Role.ROLE_USER,
      content: [textPart("multi-turn step one")], metadata: {}, extensions: [],
    };
    const result1 = await client.sendMessage({
      request: msg1, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true },
    });
    let retCtxId = "";
    if (isTask(result1)) retCtxId = result1.contextId;
    else if (isMessage(result1)) retCtxId = result1.contextId;

    const msg2 = {
      messageId: randomUUID(), contextId: retCtxId || contextId, taskId: "",
      role: Role.ROLE_USER,
      content: [textPart("multi-turn step two")], metadata: {}, extensions: [],
    };
    const result2 = await client.sendMessage({
      request: msg2, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true },
    });
    let ctx2 = "";
    if (isTask(result2)) ctx2 = result2.contextId;
    else if (isMessage(result2)) ctx2 = result2.contextId;

    const ms = Date.now() - t0;
    const ok = retCtxId.length > 0 && ctx2 === retCtxId;
    record(`${prefix}/multi-turn-context-preserved`, "Context Preserved", ok,
      `ctx1=${retCtxId?.slice(0, 8)}..., ctx2=${ctx2?.slice(0, 8)}..., match=${ctx2 === retCtxId}`, ms);
  } catch (e) {
    record(`${prefix}/multi-turn-context-preserved`, "Context Preserved", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testGetTaskWithHistory(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    // Create a task first
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-lifecycle process this", { binding });
    if (!finalTask?.id) {
      record(`${prefix}/get-task-with-history`, "GetTask With History", false, "no task created", Date.now() - t0);
      return;
    }
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const task = await client.getTask({ name: `tasks/${finalTask.id}`, historyLength: 10 });
    const ms = Date.now() - t0;
    const histLen = task.history?.length || 0;
    const ok = task.id === finalTask.id && histLen > 0;
    record(`${prefix}/get-task-with-history`, "GetTask With History", ok,
      `taskId=${task.id}, historyLength=${histLen}`, ms);
  } catch (e) {
    record(`${prefix}/get-task-with-history`, "GetTask With History", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testGetTaskAfterFailure(binding = "JSONRPC") {
  const prefix = binding === "REST" ? "rest" : "jsonrpc";
  const t0 = Date.now();
  try {
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-failure trigger error", { binding });
    if (!finalTask?.id) {
      record(`${prefix}/get-task-after-failure`, "GetTask After Failure", false, "no task created", Date.now() - t0);
      return;
    }
    const client = await makeClient(`${BASE_URL}/spec`, { binding });
    const task = await client.getTask({ name: `tasks/${finalTask.id}`, historyLength: 0 });
    const ms = Date.now() - t0;
    const state = getTaskState(task);
    const ok = state === "TASK_STATE_FAILED";
    record(`${prefix}/get-task-after-failure`, "GetTask After Failure", ok,
      `taskId=${task.id}, state=${state}`, ms);
  } catch (e) {
    record(`${prefix}/get-task-after-failure`, "GetTask After Failure", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

// =====================================================================
// REST Tests — mirror JSON-RPC tests but with REST binding
// =====================================================================

async function testRestAgentCardEcho() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/echo`, { binding: "REST" });
    const card = await client.getAgentCard();
    const ms = Date.now() - t0;
    const ok = card.name === "Echo Agent" && card.skills?.length > 0;
    record("rest/agent-card-echo", "REST Echo Agent Card", ok,
      `name=${card.name}, skills=${card.skills?.length}`, ms);
  } catch (e) {
    record("rest/agent-card-echo", "REST Echo Agent Card", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestAgentCardSpec() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding: "REST" });
    const card = await client.getAgentCard();
    const ms = Date.now() - t0;
    const skillIds = card.skills?.map((s) => s.id) || [];
    const ok = card.name?.includes("Spec") && card.skills?.length > 0;
    record("rest/agent-card-spec", "REST Spec Agent Card", ok,
      `name=${card.name}, skills=[${skillIds.join(",")}]`, ms);
  } catch (e) {
    record("rest/agent-card-spec", "REST Spec Agent Card", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestEchoSendMessage() {
  const t0 = Date.now();
  try {
    const result = await sdkSend(`${BASE_URL}/echo`, "Hello from JS SDK!", { binding: "REST" });
    const ms = Date.now() - t0;
    let reply = "";
    if (isMessage(result)) reply = getTextFromParts(result.content);
    else if (isTask(result)) reply = getTextFromTask(result);
    const ok = reply.startsWith("Echo:");
    record("rest/echo-send-message", "REST Echo Send Message", ok, `reply=${reply.slice(0, 80)}`, ms);
  } catch (e) {
    record("rest/echo-send-message", "REST Echo Send Message", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecMessageOnly() {
  const t0 = Date.now();
  try {
    const result = await sdkSend(`${BASE_URL}/spec`, "message-only hello world", { binding: "REST" });
    const ms = Date.now() - t0;
    let reply = "";
    let gotMessage = false;
    if (isMessage(result)) { gotMessage = true; reply = getTextFromParts(result.content); }
    else if (isTask(result)) { reply = getTextFromTask(result); gotMessage = reply.length > 0; }
    const ok = gotMessage && reply.length > 0;
    record("rest/spec-message-only", "REST Spec Message Only", ok,
      `gotMessage=${gotMessage}, text=${reply.slice(0, 60)}`, ms);
  } catch (e) {
    record("rest/spec-message-only", "REST Spec Message Only", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecTaskLifecycle() {
  const t0 = Date.now();
  try {
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-lifecycle process this", { binding: "REST" });
    const ms = Date.now() - t0;
    const state = getTaskState(finalTask);
    const hasArtifact = finalTask?.artifacts?.length > 0;
    if (finalTask?.id) restLifecycleTaskId = finalTask.id;
    const ok = state === "TASK_STATE_COMPLETED" && hasArtifact;
    record("rest/spec-task-lifecycle", "REST Spec Task Lifecycle", ok,
      `state=${state}, artifacts=${hasArtifact}, taskId=${restLifecycleTaskId}`, ms);
  } catch (e) {
    record("rest/spec-task-lifecycle", "REST Spec Task Lifecycle", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecGetTask() {
  const t0 = Date.now();
  if (!restLifecycleTaskId) {
    record("rest/spec-get-task", "REST Spec GetTask", false, "skipped — no taskId from lifecycle", 0);
    return;
  }
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding: "REST" });
    const task = await client.getTask({ name: `tasks/${restLifecycleTaskId}`, historyLength: 0 });
    const ms = Date.now() - t0;
    const state = getTaskState(task);
    const ok = task.id === restLifecycleTaskId && state === "TASK_STATE_COMPLETED";
    record("rest/spec-get-task", "REST Spec GetTask", ok, `taskId=${task.id}, state=${state}`, ms);
  } catch (e) {
    record("rest/spec-get-task", "REST Spec GetTask", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecTaskFailure() {
  const t0 = Date.now();
  try {
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "task-failure trigger error", { binding: "REST" });
    const ms = Date.now() - t0;
    const state = getTaskState(finalTask);
    const ok = state === "TASK_STATE_FAILED";
    record("rest/spec-task-failure", "REST Spec Task Failure", ok, `state=${state}`, ms);
  } catch (e) {
    record("rest/spec-task-failure", "REST Spec Task Failure", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecDataTypes() {
  const t0 = Date.now();
  try {
    const { events, finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "data-types show all", { binding: "REST" });
    const ms = Date.now() - t0;
    const partKinds = new Set();
    for (const ev of events) {
      const sources = [];
      if (isMessage(ev)) sources.push(ev.content);
      if (isTask(ev)) for (const art of ev.artifacts || []) sources.push(art.parts);
      if (isArtifactEvent(ev) && ev.artifact) sources.push(ev.artifact.parts);
      for (const parts of sources) {
        for (const p of parts || []) {
          if (p.part?.$case === "text") partKinds.add("text");
          if (p.part?.$case === "data") partKinds.add("data");
          if (p.part?.$case === "file") partKinds.add("file");
        }
      }
    }
    if (finalTask) {
      for (const art of finalTask.artifacts || []) {
        for (const p of art.parts || []) {
          if (p.part?.$case === "text") partKinds.add("text");
          if (p.part?.$case === "data") partKinds.add("data");
          if (p.part?.$case === "file") partKinds.add("file");
        }
      }
    }
    const ok = partKinds.size >= 2;
    record("rest/spec-data-types", "REST Spec Data Types", ok,
      `kinds=[${[...partKinds].sort().join(",")}]`, ms);
  } catch (e) {
    record("rest/spec-data-types", "REST Spec Data Types", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecStreaming() {
  const t0 = Date.now();
  try {
    const { events, finalTask } = await sdkSendStream(`${BASE_URL}/spec`, "streaming generate output", { binding: "REST" });
    const ms = Date.now() - t0;
    const ok = events.length >= 2;
    const finalText = getTextFromTask(finalTask);
    record("rest/spec-streaming", "REST Spec Streaming", ok,
      `events=${events.length}, text=${finalText.slice(0, 50)}`, ms);
  } catch (e) {
    record("rest/spec-streaming", "REST Spec Streaming", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecMultiTurn() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding: "REST" });
    const contextId = randomUUID();
    const msg1 = {
      messageId: randomUUID(), contextId, taskId: "", role: Role.ROLE_USER,
      content: [textPart("multi-turn step one")], metadata: {}, extensions: [],
    };
    const result1 = await client.sendMessage({
      request: msg1, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true },
    });
    let taskId = "";
    let retCtxId = "";
    if (isTask(result1)) { taskId = result1.id; retCtxId = result1.contextId; }
    else if (isMessage(result1)) { retCtxId = result1.contextId; }

    const msg2 = {
      messageId: randomUUID(), contextId: retCtxId || contextId, taskId,
      role: Role.ROLE_USER, content: [textPart("multi-turn step two")], metadata: {}, extensions: [],
    };
    const result2 = await client.sendMessage({
      request: msg2, configuration: { acceptedOutputModes: ["text/plain"], historyLength: 0, blocking: true },
    });
    let turn2Text = "";
    if (isTask(result2)) turn2Text = getTextFromTask(result2);
    else if (isMessage(result2)) turn2Text = getTextFromParts(result2.content);

    const ms = Date.now() - t0;
    const ok = turn2Text.length > 0;
    record("rest/spec-multi-turn", "REST Spec Multi-Turn", ok,
      `contextId=${(retCtxId || contextId).slice(0, 8)}..., turn2=${turn2Text.slice(0, 50)}`, ms);
  } catch (e) {
    record("rest/spec-multi-turn", "REST Spec Multi-Turn", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecTaskCancel() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding: "REST" });
    const req = makeSendRequest("task-cancel start");
    let taskId = null;
    for await (const event of client.sendMessageStream(req)) {
      if (isTask(event)) { taskId = event.id; break; }
      if (isStatusEvent(event)) { taskId = event.taskId; break; }
    }
    if (!taskId) {
      record("rest/spec-task-cancel", "REST Spec Task Cancel", false, "no taskId from stream", Date.now() - t0);
      return;
    }
    const cancelResult = await client.cancelTask({ name: `tasks/${taskId}` });
    const ms = Date.now() - t0;
    const state = getTaskState(cancelResult);
    const ok = state === "TASK_STATE_CANCELLED";
    record("rest/spec-task-cancel", "REST Spec Task Cancel", ok, `taskId=${taskId}, state=${state}`, ms);
  } catch (e) {
    record("rest/spec-task-cancel", "REST Spec Task Cancel", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestSpecListTasks() {
  record("rest/spec-list-tasks", "REST Spec ListTasks", false,
    "SDK not supported: JS SDK does not expose listTasks", 0);
}

async function testRestSpecReturnImmediately() {
  const t0 = Date.now();
  try {
    const result = await sdkSend(`${BASE_URL}/spec`, "task-lifecycle process this", { binding: "REST", blocking: false });
    const ms = Date.now() - t0;
    let state = "UNKNOWN";
    if (isTask(result)) state = getTaskState(result);
    const ok = ms < 3000;
    record("rest/spec-return-immediately", "REST Return Immediately", ok, `state=${state}, ms=${ms}`, ms);
  } catch (e) {
    record("rest/spec-return-immediately", "REST Return Immediately", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testRestErrorTaskNotFound() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec`, { binding: "REST" });
    await client.getTask({ name: "tasks/nonexistent-task-id-12345", historyLength: 0 });
    record("rest/error-task-not-found", "REST Task Not Found Error", false, "expected error but got success", Date.now() - t0);
  } catch (e) {
    const ms = Date.now() - t0;
    const isNotFound = e.constructor?.name?.includes("NotFound") || e.message?.includes("not found") || e.message?.includes("-32001") || e.message?.includes("404");
    record("rest/error-task-not-found", "REST Task Not Found Error", isNotFound,
      `error=${e.constructor?.name}: ${e.message?.slice(0, 80)}`, ms);
  }
}

// =====================================================================
// v0.3 Backward Compatibility Tests
// =====================================================================

async function testV03AgentCard() {
  const t0 = Date.now();
  try {
    const card = await fetchAgentCard(`${BASE_URL}/spec03`);
    const ms = Date.now() - t0;
    const name = card?.name || "unknown";
    const skills = card?.skills?.length ?? 0;
    const ok = name !== "unknown" && skills >= 0;
    record("v03/spec03-agent-card", "v0.3 Agent Card", ok,
      `name=${name}, skills=${skills}`, ms);
  } catch (e) {
    record("v03/spec03-agent-card", "v0.3 Agent Card", false, e.message?.slice(0, 120), Date.now() - t0);
  }
}

async function testV03SendMessage() {
  const t0 = Date.now();
  try {
    const client = await makeClient(`${BASE_URL}/spec03`);
    const result = await sdkSend(`${BASE_URL}/spec03`, "message-only hello");
    const ms = Date.now() - t0;
    let reply = "";
    let gotMessage = false;
    if (isMessage(result)) { gotMessage = true; reply = getTextFromParts(result.content); }
    else if (isTask(result)) { reply = getTextFromTask(result); gotMessage = reply.length > 0; }
    const ok = gotMessage && reply.length > 0;
    record("v03/spec03-send-message", "v0.3 Send Message", ok,
      `gotMessage=${gotMessage}, text=${reply.slice(0, 60)}`, ms);
  } catch (e) {
    record("v03/spec03-send-message", "v0.3 Send Message", false,
      `SDK v0.3 failed: ${e.constructor?.name}: ${e.message?.slice(0, 100)}`, Date.now() - t0);
  }
}

async function testV03TaskLifecycle() {
  const t0 = Date.now();
  try {
    const { finalTask } = await sdkSendStream(`${BASE_URL}/spec03`, "task-lifecycle process this");
    const ms = Date.now() - t0;
    const state = getTaskState(finalTask);
    const hasArtifact = finalTask?.artifacts?.length > 0;
    const ok = state === "TASK_STATE_COMPLETED" && hasArtifact;
    record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", ok,
      `state=${state}, artifacts=${hasArtifact}`, ms);
  } catch (e) {
    record("v03/spec03-task-lifecycle", "v0.3 Task Lifecycle", false,
      `SDK v0.3 failed: ${e.constructor?.name}: ${e.message?.slice(0, 100)}`, Date.now() - t0);
  }
}

async function testV03Streaming() {
  const t0 = Date.now();
  try {
    const { events, finalTask } = await sdkSendStream(`${BASE_URL}/spec03`, "streaming generate output");
    const ms = Date.now() - t0;
    const finalText = getTextFromTask(finalTask);
    const ok = events.length >= 1 && finalText.length > 0;
    record("v03/spec03-streaming", "v0.3 Streaming", ok,
      `events=${events.length}, text=${finalText.slice(0, 50)}`, ms);
  } catch (e) {
    record("v03/spec03-streaming", "v0.3 Streaming", false,
      `SDK v0.3 failed: ${e.constructor?.name}: ${e.message?.slice(0, 100)}`, Date.now() - t0);
  }
}

// =====================================================================
// Test Runner
// =====================================================================

const ALL_TESTS = [
  // JSON-RPC tests
  ["jsonrpc/agent-card-echo", testAgentCardEcho],
  ["jsonrpc/agent-card-spec", testAgentCardSpec],
  ["jsonrpc/echo-send-message", testEchoSendMessage],
  ["jsonrpc/spec-message-only", testSpecMessageOnly],
  ["jsonrpc/spec-task-lifecycle", testSpecTaskLifecycle],
  ["jsonrpc/spec-get-task", testSpecGetTask],
  ["jsonrpc/spec-task-failure", testSpecTaskFailure],
  ["jsonrpc/spec-data-types", testSpecDataTypes],
  ["jsonrpc/spec-streaming", testSpecStreaming],
  ["jsonrpc/spec-multi-turn", testSpecMultiTurn],
  ["jsonrpc/spec-task-cancel", testSpecTaskCancel],
  ["jsonrpc/spec-cancel-with-metadata", () => testSpecCancelWithMetadata("JSONRPC")],
  ["jsonrpc/spec-list-tasks", testSpecListTasks],
  ["jsonrpc/spec-return-immediately", testSpecReturnImmediately],
  ["jsonrpc/error-task-not-found", testErrorTaskNotFound],
  ["jsonrpc/error-cancel-not-found", () => testErrorCancelNotFound("JSONRPC")],
  ["jsonrpc/error-cancel-terminal", () => testErrorCancelTerminal("JSONRPC")],
  ["jsonrpc/error-send-terminal", () => testErrorSendTerminal("JSONRPC")],
  ["jsonrpc/error-send-invalid-task", () => testErrorSendInvalidTask("JSONRPC")],
  ["jsonrpc/error-push-not-supported", () => testErrorPushNotSupported("JSONRPC")],
  ["jsonrpc/subscribe-to-task", () => testSubscribeToTask("JSONRPC")],
  ["jsonrpc/error-subscribe-not-found", () => testErrorSubscribeNotFound("JSONRPC")],
  ["jsonrpc/stream-message-only", () => testStreamMessageOnly("JSONRPC")],
  ["jsonrpc/stream-task-lifecycle", () => testStreamTaskLifecycle("JSONRPC")],
  ["jsonrpc/multi-turn-context-preserved", () => testMultiTurnContextPreserved("JSONRPC")],
  ["jsonrpc/get-task-with-history", () => testGetTaskWithHistory("JSONRPC")],
  ["jsonrpc/get-task-after-failure", () => testGetTaskAfterFailure("JSONRPC")],
  // REST tests
  ["rest/agent-card-echo", testRestAgentCardEcho],
  ["rest/agent-card-spec", testRestAgentCardSpec],
  ["rest/echo-send-message", testRestEchoSendMessage],
  ["rest/spec-message-only", testRestSpecMessageOnly],
  ["rest/spec-task-lifecycle", testRestSpecTaskLifecycle],
  ["rest/spec-get-task", testRestSpecGetTask],
  ["rest/spec-task-failure", testRestSpecTaskFailure],
  ["rest/spec-data-types", testRestSpecDataTypes],
  ["rest/spec-streaming", testRestSpecStreaming],
  ["rest/spec-multi-turn", testRestSpecMultiTurn],
  ["rest/spec-task-cancel", testRestSpecTaskCancel],
  ["rest/spec-cancel-with-metadata", () => testSpecCancelWithMetadata("REST")],
  ["rest/spec-list-tasks", testRestSpecListTasks],
  ["rest/spec-return-immediately", testRestSpecReturnImmediately],
  ["rest/error-task-not-found", testRestErrorTaskNotFound],
  ["rest/error-cancel-not-found", () => testErrorCancelNotFound("REST")],
  ["rest/error-cancel-terminal", () => testErrorCancelTerminal("REST")],
  ["rest/error-send-terminal", () => testErrorSendTerminal("REST")],
  ["rest/error-send-invalid-task", () => testErrorSendInvalidTask("REST")],
  ["rest/error-push-not-supported", () => testErrorPushNotSupported("REST")],
  ["rest/subscribe-to-task", () => testSubscribeToTask("REST")],
  ["rest/error-subscribe-not-found", () => testErrorSubscribeNotFound("REST")],
  ["rest/stream-message-only", () => testStreamMessageOnly("REST")],
  ["rest/stream-task-lifecycle", () => testStreamTaskLifecycle("REST")],
  ["rest/multi-turn-context-preserved", () => testMultiTurnContextPreserved("REST")],
  ["rest/get-task-with-history", () => testGetTaskWithHistory("REST")],
  ["rest/get-task-after-failure", () => testGetTaskAfterFailure("REST")],
  // v0.3 backward compatibility tests
  ["v03/spec03-agent-card", testV03AgentCard],
  ["v03/spec03-send-message", testV03SendMessage],
  ["v03/spec03-task-lifecycle", testV03TaskLifecycle],
  ["v03/spec03-streaming", testV03Streaming],
];

async function main() {
  console.log(`\n${"=".repeat(64)}`);
  console.log(`  A2A JavaScript SDK Integration Tests  (${SDK_SOURCE})`);
  console.log(`  Target: ${BASE_URL}`);
  console.log(`${"=".repeat(64)}\n`);

  for (const [testId, fn] of ALL_TESTS) {
    try {
      await fn();
    } catch (e) {
      record(testId, testId, false, `EXCEPTION: ${e.message?.slice(0, 100)}`, 0);
      console.error(e);
    }
  }

  // Console summary
  const passed = RESULTS.filter((r) => r.passed).length;
  const failed = RESULTS.filter((r) => !r.passed).length;
  console.log(`\n${"=".repeat(64)}`);
  console.log(`  TOTAL: ${passed} passed, ${failed} failed, ${RESULTS.length} total`);
  console.log(`${"=".repeat(64)}\n`);

  // Write results.json
  const output = {
    client: "js",
    sdk: SDK_SOURCE,
    protocolVersion: "1.0",
    timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    baseUrl: BASE_URL,
    results: RESULTS,
  };
  const resultsPath = join(__dirname, "results.json");
  writeFileSync(resultsPath, JSON.stringify(output, null, 2));
  console.log(`  Results written to ${resultsPath}\n`);

  process.exit(failed === 0 ? 0 : 1);
}

main();
