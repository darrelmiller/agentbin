/**
 * V1 wire-format compatibility layer for the a2a-js SDK.
 *
 * The SDK (epic/1.0_breaking_changes, v0.3.10) has a mismatch with the v1.0
 * server wire format:
 *   - JSON-RPC method names: SDK sends "message/send" → server expects "SendMessage"
 *   - Message field: SDK serializes "content" → server expects "parts"
 *   - JSON-RPC response: SDK expects result.payload.$case → server sends result.{message|task}
 *
 * This module provides:
 *   - V1JsonRpcTransport: A Transport implementation that speaks correct v1.0 JSON-RPC
 *   - createV1RestFetch(): A fetch wrapper that fixes content↔parts for the REST transport
 */

import {
  Message,
  Task,
  TaskStatusUpdateEvent,
  TaskArtifactUpdateEvent,
  SendMessageRequest,
  GetTaskRequest,
  CancelTaskRequest,
  TaskSubscriptionRequest,
  CreateTaskPushNotificationConfigRequest,
  GetTaskPushNotificationConfigRequest,
  ListTaskPushNotificationConfigRequest,
  DeleteTaskPushNotificationConfigRequest,
  TaskPushNotificationConfig,
} from "@a2a-js/sdk";

import {
  TaskNotFoundError,
  TaskNotCancelableError,
  PushNotificationNotSupportedError,
  UnsupportedOperationError,
  ContentTypeNotSupportedError,
} from "@a2a-js/sdk/client";

// ---- JSON-RPC method name mapping (v0.3 → v1.0) ----
const V1_METHODS = {
  "message/send": "SendMessage",
  "message/stream": "SendStreamingMessage",
  "tasks/get": "GetTask",
  "tasks/cancel": "CancelTask",
  "tasks/resubscribe": "SubscribeToTask",
  "tasks/pushNotificationConfig/set": "CreateTaskPushNotificationConfig",
  "tasks/pushNotificationConfig/get": "GetTaskPushNotificationConfig",
  "tasks/pushNotificationConfig/list": "ListTaskPushNotificationConfig",
  "tasks/pushNotificationConfig/delete": "DeleteTaskPushNotificationConfig",
  "agent/getAuthenticatedExtendedCard": "GetAuthenticatedExtendedCard",
};

// ---- State normalization (server uses American "CANCELED", SDK uses British "CANCELLED") ----
const STATE_NORMALIZE = {
  "TASK_STATE_CANCELED": "TASK_STATE_CANCELLED",
};

// ---- Field transforms ----

/**
 * Recursively transform outbound JSON: rename "content" → "parts" in
 * objects that look like Messages (identified by having "messageId").
 */
export function transformOutbound(obj) {
  if (obj === null || obj === undefined || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(transformOutbound);
  const result = {};
  const isMessage = "messageId" in obj || "message_id" in obj;
  for (const [key, val] of Object.entries(obj)) {
    if (key === "content" && isMessage) {
      result.parts = transformOutbound(val);
    } else {
      result[key] = transformOutbound(val);
    }
  }
  return result;
}

/**
 * Recursively transform inbound JSON: rename "parts" → "content" in
 * objects that look like Messages (identified by having "messageId").
 * Artifact.parts is NOT renamed (Artifacts don't have messageId).
 * Also normalizes state enum strings (CANCELED → CANCELLED).
 */
export function transformInbound(obj) {
  if (obj === null || obj === undefined || typeof obj !== "object") return obj;
  if (Array.isArray(obj)) return obj.map(transformInbound);
  const result = {};
  const isMessage = "messageId" in obj || "message_id" in obj;
  for (const [key, val] of Object.entries(obj)) {
    if (key === "parts" && isMessage) {
      result.content = transformInbound(val);
    } else if (key === "state" && typeof val === "string" && STATE_NORMALIZE[val]) {
      result[key] = STATE_NORMALIZE[val];
    } else {
      result[key] = transformInbound(val);
    }
  }
  return result;
}

// ---- JSON-RPC error mapping ----

function mapRpcError(error) {
  const code = error?.code;
  const msg = error?.message || "Unknown JSON-RPC error";
  const data = error?.data;
  switch (code) {
    case -32001:
      return new TaskNotFoundError(msg);
    case -32002:
      return new TaskNotCancelableError(msg);
    case -32003:
      return new PushNotificationNotSupportedError(msg);
    case -32004:
      return new UnsupportedOperationError(msg);
    case -32005:
      return new ContentTypeNotSupportedError(msg);
    default: {
      const e = new Error(`JSON-RPC error: ${msg} (Code: ${code}) Data: ${JSON.stringify(data)}`);
      e.code = code;
      return e;
    }
  }
}

// ---- Response parsers (server wire → SDK proto objects) ----

function parseSendResult(result) {
  const t = transformInbound(result);
  if (t.task) return Task.fromJSON(t.task);
  if (t.message) return Message.fromJSON(t.message);
  if (t.msg) return Message.fromJSON(t.msg);
  // The entire result might BE a task or message directly
  if (t.id && t.status) return Task.fromJSON(t);
  if (t.messageId) return Message.fromJSON(t);
  throw new Error("Invalid SendMessage response: " + JSON.stringify(result).slice(0, 200));
}

function parseStreamEvent(data) {
  const t = transformInbound(data);
  if (t.task) return Task.fromJSON(t.task);
  if (t.message) return Message.fromJSON(t.message);
  if (t.msg) return Message.fromJSON(t.msg);
  if (t.statusUpdate) return TaskStatusUpdateEvent.fromJSON(t.statusUpdate);
  if (t.status_update) return TaskStatusUpdateEvent.fromJSON(t.status_update);
  if (t.artifactUpdate) return TaskArtifactUpdateEvent.fromJSON(t.artifactUpdate);
  if (t.artifact_update) return TaskArtifactUpdateEvent.fromJSON(t.artifact_update);
  // Direct types
  if (t.id && t.status && t.artifacts) return Task.fromJSON(t);
  if (t.messageId) return Message.fromJSON(t);
  if (t.taskId && t.status && !t.artifact) return TaskStatusUpdateEvent.fromJSON(t);
  if (t.taskId && t.artifact) return TaskArtifactUpdateEvent.fromJSON(t);
  throw new Error("Unknown stream event: " + JSON.stringify(data).slice(0, 200));
}

// ---- SSE parser ----

async function* parseSseLines(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith("data:")) {
          const jsonStr = line.slice(5).trim();
          if (jsonStr) yield jsonStr;
        }
      }
    }
    // flush
    if (buffer.startsWith("data:")) {
      const jsonStr = buffer.slice(5).trim();
      if (jsonStr) yield jsonStr;
    }
  } finally {
    reader.releaseLock();
  }
}

// ====================================================================
// V1JsonRpcTransport — implements the SDK Transport interface
// ====================================================================

export class V1JsonRpcTransport {
  constructor({ endpoint, fetchImpl }) {
    this.endpoint = endpoint;
    this._fetch = fetchImpl || globalThis.fetch;
    this._nextId = 1;
  }

  /** Low-level JSON-RPC call returning the parsed result. */
  async _rpc(v03Method, params, options) {
    const method = V1_METHODS[v03Method] || v03Method;
    const body = {
      jsonrpc: "2.0",
      method,
      id: this._nextId++,
    };
    if (params !== undefined) {
      body.params = transformOutbound(params);
    }
    const resp = await this._fetch(this.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: options?.signal,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
    }
    const json = await resp.json();
    if (json.error) throw mapRpcError(json.error);
    return json.result;
  }

  /** Low-level JSON-RPC streaming call returning the Response. */
  async _rpcStream(v03Method, params, options) {
    const method = V1_METHODS[v03Method] || v03Method;
    const id = this._nextId++;
    const body = { jsonrpc: "2.0", method, id };
    if (params !== undefined) {
      body.params = transformOutbound(params);
    }
    const resp = await this._fetch(this.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify(body),
      signal: options?.signal,
    });
    return { response: resp, requestId: id };
  }

  // --- Transport interface methods ---

  async getExtendedAgentCard(options) {
    const result = await this._rpc(
      "agent/getAuthenticatedExtendedCard",
      undefined,
      options,
    );
    return result;
  }

  async sendMessage(params, options) {
    const toJson = safeToJSON(SendMessageRequest, params);
    const result = await this._rpc("message/send", toJson, options);
    return parseSendResult(result);
  }

  async *sendMessageStream(params, options) {
    const toJson = safeToJSON(SendMessageRequest, params);
    const { response, requestId } = await this._rpcStream(
      "message/stream",
      toJson,
      options,
    );

    const ct = response.headers.get("content-type") || "";
    if (!ct.includes("text/event-stream")) {
      // Non-streaming error or fallback response
      const json = await response.json();
      if (json.error) throw mapRpcError(json.error);
      yield parseSendResult(json.result ?? json);
      return;
    }

    for await (const jsonStr of parseSseLines(response)) {
      let parsed;
      try {
        parsed = JSON.parse(jsonStr);
      } catch {
        continue;
      }
      if (parsed.error) throw mapRpcError(parsed.error);
      const result = parsed.result ?? parsed;
      yield parseStreamEvent(result);
    }
  }

  async setTaskPushNotificationConfig(params, options) {
    const toJson = safeToJSON(CreateTaskPushNotificationConfigRequest, params);
    const result = await this._rpc(
      "tasks/pushNotificationConfig/set",
      toJson,
      options,
    );
    return TaskPushNotificationConfig.fromJSON(result);
  }

  async getTaskPushNotificationConfig(params, options) {
    const toJson = safeToJSON(GetTaskPushNotificationConfigRequest, params);
    const result = await this._rpc(
      "tasks/pushNotificationConfig/get",
      toJson,
      options,
    );
    return TaskPushNotificationConfig.fromJSON(result);
  }

  async listTaskPushNotificationConfig(params, options) {
    const toJson = safeToJSON(ListTaskPushNotificationConfigRequest, params);
    const result = await this._rpc(
      "tasks/pushNotificationConfig/list",
      toJson,
      options,
    );
    const configs = result.configs || result.pushNotificationConfigs || [];
    return configs.map((c) => TaskPushNotificationConfig.fromJSON(c));
  }

  async deleteTaskPushNotificationConfig(params, options) {
    const toJson = safeToJSON(DeleteTaskPushNotificationConfigRequest, params);
    await this._rpc(
      "tasks/pushNotificationConfig/delete",
      toJson,
      options,
    );
  }

  async getTask(params, options) {
    const toJson = safeToJSON(GetTaskRequest, params);
    const result = await this._rpc("tasks/get", toV1TaskParams(toJson), options);
    return Task.fromJSON(transformInbound(result));
  }

  async cancelTask(params, options) {
    const toJson = safeToJSON(CancelTaskRequest, params);
    const v1Params = toV1TaskParams(toJson);
    // Preserve metadata if present (CancelTaskRequest.toJSON drops it)
    if (params.metadata && Object.keys(params.metadata).length > 0) {
      v1Params.metadata = params.metadata;
    }
    const result = await this._rpc("tasks/cancel", v1Params, options);
    return Task.fromJSON(transformInbound(result));
  }

  async *resubscribeTask(params, options) {
    const toJson = safeToJSON(TaskSubscriptionRequest, params);
    const { response, requestId } = await this._rpcStream(
      "tasks/resubscribe",
      toV1TaskParams(toJson),
      options,
    );

    const ct = response.headers.get("content-type") || "";
    if (!ct.includes("text/event-stream")) {
      const json = await response.json();
      if (json.error) throw mapRpcError(json.error);
      return;
    }

    for await (const jsonStr of parseSseLines(response)) {
      let parsed;
      try {
        parsed = JSON.parse(jsonStr);
      } catch {
        continue;
      }
      if (parsed.error) throw mapRpcError(parsed.error);
      const result = parsed.result ?? parsed;
      yield parseStreamEvent(result);
    }
  }
}

// ====================================================================
// REST fetch wrapper
// ====================================================================

/**
 * Creates a custom fetch function for use with the SDK's RestTransport.
 * Transforms request bodies (content→parts) and response bodies (parts→content)
 * to bridge the SDK's proto field naming with the v1.0 wire format.
 */
export function createV1RestFetch(realFetch = globalThis.fetch) {
  return async function v1RestFetch(url, init) {
    // Transform outbound request body
    if (init?.body && typeof init.body === "string") {
      try {
        const body = JSON.parse(init.body);
        init = { ...init, body: JSON.stringify(transformOutbound(body)) };
      } catch {
        /* not JSON — leave as-is */
      }
    }

    const response = await realFetch(url, init);
    const ct = response.headers.get("content-type") || "";

    if (ct.includes("text/event-stream")) {
      return transformSseResponse(response);
    }

    // Transform JSON response body
    return transformJsonResponse(response);
  };
}

async function transformJsonResponse(response) {
  const text = await response.text();
  let newBody = text;
  try {
    const data = JSON.parse(text);
    newBody = JSON.stringify(transformInbound(data));
  } catch {
    /* not JSON */
  }
  return new Response(newBody, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

function transformSseResponse(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";

  const transformedBody = new ReadableStream({
    async pull(controller) {
      const { done, value } = await reader.read();
      if (done) {
        if (buffer.trim()) {
          controller.enqueue(encoder.encode(processSseLine(buffer)));
        }
        controller.close();
        return;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop();

      let output = "";
      for (const line of lines) {
        output += processSseLine(line) + "\n";
      }
      if (output) {
        controller.enqueue(encoder.encode(output));
      }
    },
  });

  return new Response(transformedBody, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

function processSseLine(line) {
  if (!line.startsWith("data:")) return line;
  const jsonStr = line.slice(5).trim();
  if (!jsonStr) return line;
  try {
    const data = JSON.parse(jsonStr);
    return "data: " + JSON.stringify(transformInbound(data));
  } catch {
    return line;
  }
}

// ---- Helpers ----

function safeToJSON(msgFns, params) {
  if (msgFns?.toJSON) {
    try {
      return msgFns.toJSON(params);
    } catch {
      return params;
    }
  }
  return params;
}

/**
 * Extract a bare task ID from a resource name like "tasks/{id}".
 * The SDK uses resource names (name: "tasks/abc") but the v1.0 JSON-RPC
 * server expects a bare ID (id: "abc").
 */
function extractTaskId(nameOrId) {
  if (!nameOrId) return nameOrId;
  const match = nameOrId.match(/^tasks\/(.+)$/);
  return match ? match[1] : nameOrId;
}

/**
 * Transform GetTaskRequest/CancelTaskRequest/TaskSubscriptionRequest params
 * from SDK resource-name format ({name: "tasks/id"}) to v1.0 JSON-RPC format ({id: "id"}).
 */
function toV1TaskParams(params) {
  if (!params) return params;
  const result = { ...params };
  if (result.name) {
    result.id = extractTaskId(result.name);
    delete result.name;
  }
  return result;
}
