"use client";

import { useEffect, useRef, useState } from "react";
import { createChat, generateReview, getChat, listChats, sendMessage } from "@/lib/chats";
import RobotIcon from "./RobotIcon";
import MessageBubble from "./MessageBubble";
import PressReviews from "./PressReviews";
import ReviewDialog from "./ReviewDialog";
import styles from "./ChatWorkspace.module.css";

function updateAddress(id, view = "chat") {
  const params = new URLSearchParams();
  if (id) params.set("chat", id);
  if (view === "reviews") params.set("view", "reviews");
  window.history.replaceState(null, "", params.size ? `/?${params}` : "/");
}

export default function ChatWorkspace({ user, onLogout, sessionError }) {
  const [chats, setChats] = useState([]);
  const [chat, setChat] = useState(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingChat, setIsLoadingChat] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [pendingMessage, setPendingMessage] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState("chat");
  const [showReviewDialog, setShowReviewDialog] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const messageInput = useRef(null);
  const bottom = useRef(null);
  const mutation = useRef(false);
  const selection = useRef(0);
  const busy = isCreating || isSending || isLoadingChat || isLoading || isGenerating;

  useEffect(() => {
    const controller = new AbortController();
    async function initialize() {
      try {
        const items = await listChats({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setChats(items);
        const params = new URLSearchParams(window.location.search);
        setView(params.get("view") === "reviews" ? "reviews" : "chat");
        const requestedId = Number(params.get("chat"));
        if (Number.isSafeInteger(requestedId) && requestedId > 0) {
          const saved = await getChat(requestedId, { signal: controller.signal });
          if (!controller.signal.aborted) setChat(saved);
        }
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (cause.status === 401) onLogout();
        else {
          setError(cause.message);
          if (cause.status === 404) updateAddress(null);
        }
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }
    initialize();
    return () => controller.abort();
  }, [onLogout, attempt]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [chat?.messages.length, pendingMessage]);

  function handleError(cause) {
    if (cause.status === 401) onLogout();
    else setError(cause.message);
  }

  function rememberChat(saved) {
    const { id, title, created_at, updated_at } = saved;
    setChats((previous) => [
      { id, title, created_at, updated_at }, ...previous.filter((item) => item.id !== id),
    ].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at) || b.id - a.id));
  }

  async function startChat() {
    if (mutation.current) return;
    mutation.current = true;
    setIsCreating(true);
    setError("");
    try {
      const saved = await createChat();
      setChat(saved);
      setView("chat");
      rememberChat(saved);
      setDraft("");
      setHistoryOpen(false);
      updateAddress(saved.id);
    } catch (cause) {
      handleError(cause);
    } finally {
      mutation.current = false;
      setIsCreating(false);
      requestAnimationFrame(() => messageInput.current?.focus());
    }
  }

  async function openChat(id) {
    if (mutation.current) return;
    const requestId = ++selection.current;
    setIsLoadingChat(true);
    setError("");
    try {
      const saved = await getChat(id);
      if (requestId !== selection.current) return;
      setChat(saved);
      setView("chat");
      setDraft("");
      setHistoryOpen(false);
      updateAddress(id);
    } catch (cause) {
      if (requestId === selection.current) handleError(cause);
    } finally {
      if (requestId === selection.current) setIsLoadingChat(false);
    }
  }

  async function submitMessage(event) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || mutation.current || busy) return;
    mutation.current = true;
    setIsSending(true);
    setError("");
    setPendingMessage({ role: "user", content, timestamp: new Date().toISOString() });
    let activeChat = chat;
    try {
      if (!activeChat) {
        activeChat = await createChat();
        setChat(activeChat);
        rememberChat(activeChat);
        updateAddress(activeChat.id);
      }
      const saved = await sendMessage(activeChat.id, content);
      setChat(saved);
      rememberChat(saved);
      setDraft("");
    } catch (cause) {
      handleError(cause);
      if (cause.status === 409 && activeChat) {
        try { setChat(await getChat(activeChat.id)); } catch (refreshError) { handleError(refreshError); }
      }
    } finally {
      mutation.current = false;
      setIsSending(false);
      setPendingMessage(null);
      requestAnimationFrame(() => messageInput.current?.focus());
    }
  }

  function goHome() {
    setChat(null);
    setDraft("");
    setError("");
    setView("chat");
    updateAddress(null);
  }

  function changeView(nextView) {
    setView(nextView);
    setHistoryOpen(false);
    updateAddress(chat?.id, nextView);
  }

  async function createReview(topic) {
    if (mutation.current || !chat) return;
    mutation.current = true;
    setIsGenerating(true);
    try {
      await generateReview(chat.id, topic);
      setShowReviewDialog(false);
      changeView("reviews");
    } catch (cause) {
      if (cause.status === 401) onLogout();
      throw cause;
    } finally {
      mutation.current = false;
      setIsGenerating(false);
    }
  }

  return (
    <div className={styles.page}>
      <a className={styles.skipLink} href="#conversation">Aller à la discussion</a>
      <aside className={styles.sidebar} aria-label="Vos discussions">
        <div className={styles.brand}>NEWSFOUNDRY <RobotIcon size={18} /></div>
        <button className={styles.mobileToggle} type="button" onClick={() => setHistoryOpen(!historyOpen)} aria-expanded={historyOpen} aria-controls="chat-history">
          {historyOpen ? "Masquer les discussions" : "Afficher les discussions"}
        </button>
        <div className={`${styles.sidebarContent} ${historyOpen ? styles.historyOpen : ""}`} id="chat-history">
          <div className={styles.newChat}>
            <button type="button" onClick={startChat} disabled={busy}>
              {isCreating ? "Création…" : "+ Nouvelle discussion"}
            </button>
          </div>
          <nav className={styles.history} aria-label="Historique des discussions">
            {isLoading && <p className={styles.emptyHistory} role="status">Chargement des discussions…</p>}
            {!isLoading && !chats.length && <p className={styles.emptyHistory}>Vos discussions apparaîtront ici.</p>}
            {chats.map((item) => (
              <button key={item.id} type="button" onClick={() => openChat(item.id)} disabled={busy} className={`${styles.historyItem} ${chat?.id === item.id ? styles.selected : ""}`} aria-current={chat?.id === item.id ? "true" : undefined}>
                <span>{item.title}</span>
                <time dateTime={item.created_at}>{new Intl.DateTimeFormat("fr-FR").format(new Date(item.created_at))}</time>
              </button>
            ))}
          </nav>
          <footer className={styles.account}>
            <p>{user.email}</p>
            <button type="button" onClick={onLogout}>Se déconnecter</button>
          </footer>
        </div>
      </aside>
      <div className={styles.workspace}>
        <header className={styles.header}>
          <div className={styles.headerMain}>
          {chat && view === "chat" ? (
            <>
              <button className={styles.back} type="button" onClick={goHome} disabled={busy} aria-label="Retour à l’accueil">←</button>
              <div className={styles.heading}><h1>{chat.title}</h1><p>Conversation active</p></div>
            </>
          ) : (
            <nav className={styles.tabs} aria-label="Espace de travail">
              <button type="button" onClick={() => changeView("chat")} disabled={busy} aria-pressed={view === "chat"}>Chat</button>
              <button type="button" onClick={() => changeView("reviews")} disabled={busy} aria-pressed={view === "reviews"}>Revue de presse</button>
            </nav>
          )}
          </div>
          {chat && view === "chat" && (
            <div className={styles.headerActions}>
              <button className={styles.reviewsButton} type="button" onClick={() => changeView("reviews")} disabled={busy}>Mes revues</button>
              <button className={styles.generateButton} type="button" onClick={() => setShowReviewDialog(true)} disabled={busy || !chat.messages.some((message) => message.role === "user")}>Générer la revue de presse</button>
            </div>
          )}
        </header>
        <main id="conversation" className={styles.conversation} tabIndex={-1}>
          {view === "reviews" ? <PressReviews onOpenChat={openChat} onLogout={onLogout} disabled={busy} /> : isLoadingChat || isLoading ? (
            <p className={styles.loading} role="status">Chargement de la discussion…</p>
          ) : !chat?.messages.length && !pendingMessage ? (
            <section className={styles.welcome} aria-labelledby="welcome-title">
              <RobotIcon size={80} />
              {chat ? <h2 id="welcome-title">Assistant Revue de Presse IA</h2> : <h1 id="welcome-title">Assistant Revue de Presse IA</h1>}
              <p>Posez-moi vos questions ou explorez un sujet pour démarrer une discussion.</p>
              <div className={styles.examples}>
                <strong>Exemples :</strong>
                {["Quels sont les grands enjeux de la transition énergétique ?", "Explique les applications de l’IA dans la santé", "Quels sont les principaux indicateurs économiques ?"].map((example) => (
                  <button key={example} type="button" onClick={() => { setDraft(example); messageInput.current?.focus(); }}>{example}</button>
                ))}
              </div>
            </section>
          ) : (
            <div className={styles.messages} role="log" aria-label="Messages de la discussion" aria-live="polite" aria-relevant="additions">
              {chat?.messages.map((message, index) => <MessageBubble key={`${chat.id}-${index}`} message={message} />)}
              {pendingMessage && <MessageBubble message={pendingMessage} />}
              {isSending && <p className={styles.thinking} role="status">L’assistant rédige sa réponse<span aria-hidden="true">…</span></p>}
              <div ref={bottom} />
            </div>
          )}
        </main>
        {(error || sessionError) && (
          <div className={styles.error} role="alert">
            <p>{error || sessionError}</p>
            <button type="button" disabled={busy} onClick={() => { setError(""); setIsLoading(true); setAttempt(attempt + 1); }}>Recharger les discussions</button>
          </div>
        )}
        {view === "chat" && <form method="post" className={styles.composer} onSubmit={submitMessage} aria-busy={isSending}>
          <label className={styles.srOnly} htmlFor="message">Votre message</label>
          <textarea ref={messageInput} id="message" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Tapez votre message ici…" rows={2} maxLength={4000} disabled={busy} required />
          <button type="submit" disabled={busy || !draft.trim()} aria-label={isSending ? "Envoi en cours" : "Envoyer le message"}>
            {isSending ? <span className={styles.spinner} aria-hidden="true" /> : (
              <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m22 2-7 20-4-9-9-4L22 2Zm0 0L11 13" /></svg>
            )}
          </button>
        </form>}
      </div>
      {showReviewDialog && <ReviewDialog onClose={() => setShowReviewDialog(false)} onGenerate={createReview} isGenerating={isGenerating} />}
    </div>
  );
}
