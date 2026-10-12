import { apiRequest, getToken } from "./auth";

function chatRequest(path, options = {}, timeout) {
  const token = getToken();
  if (!token) {
    const error = new Error("Votre session a expiré. Reconnectez-vous.");
    error.status = 401;
    throw error;
  }
  return apiRequest(path, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
  }, timeout);
}

export function listChats(options) {
  return chatRequest("/chats", options);
}

export function createChat() {
  return chatRequest("/chats", { method: "POST" }, 15000);
}

export function getChat(id, options) {
  return chatRequest(`/chats/${id}`, options);
}

export function sendMessage(id, content) {
  return chatRequest(`/chats/${id}/messages`, {
    method: "POST", body: JSON.stringify({ content }),
  }, 65000);
}

export function listReviews(options) {
  return chatRequest("/reviews", options);
}

export function generateReview(id, topic) {
  return chatRequest(`/chats/${id}/reviews`, {
    method: "POST", body: JSON.stringify({ topic }),
  }, 65000);
}
