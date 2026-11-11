import api from "./api";

export function addFeedback(payload) {
  return api.post("/feedback", payload);
}

export function listFeedback(traceId) {
  return api.get("/feedback", { params: { trace_id: traceId } });
}

export function deleteFeedback(fid) {
  return api.delete("/feedback/" + fid);
}
