import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { listReviews } from "@/lib/chats";
import styles from "./PressReviews.module.css";

function ReviewCard({ review, onOpenChat, disabled }) {
  const [copyStatus, setCopyStatus] = useState("");

  async function copy() {
    try {
      const text = [review.title, review.summary, ...review.articles.map((article) => (
        `${article.title}\n${article.summary}${article.url ? `\n${article.url}` : ""}`
      ))].join("\n\n");
      await navigator.clipboard.writeText(text);
      setCopyStatus("Revue copiée.");
    } catch {
      setCopyStatus("La copie a échoué. Vous pouvez sélectionner le texte manuellement.");
    }
  }

  return (
    <article className={styles.card} aria-labelledby={`review-${review.id}`}>
      <div className={styles.cardHeader}>
        <div>
          <h2 id={`review-${review.id}`}>{review.title}</h2>
          <time dateTime={review.created_at}>{new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeStyle: "short" }).format(new Date(review.created_at))}</time>
          <p className={styles.topic}>Sujet : {review.topic}</p>
          <button className={styles.chatLink} type="button" onClick={() => onOpenChat(review.chat_id)} disabled={disabled}>Discussion : {review.chat_title}</button>
        </div>
        <button className={styles.copy} type="button" onClick={copy}>Copier</button>
      </div>
      {copyStatus && <p className={styles.status} role="status">{copyStatus}</p>}
      <div className={styles.content}>
        <h3>Synthèse générale</h3>
        <ReactMarkdown skipHtml>{review.summary}</ReactMarkdown>
        {review.articles.length > 0 && <h3>Articles de la revue</h3>}
        {review.articles.map((article, index) => (
          <section key={`${review.id}-${index}`} className={styles.article}>
            <h4>{article.title}</h4>
            <ReactMarkdown skipHtml>{article.summary}</ReactMarkdown>
            {article.published_at && <p className={styles.sourceDate}>Publication : {article.published_at}</p>}
            {article.url && <a href={article.url} target="_blank" rel="noopener noreferrer">Lire l’article : {article.title}</a>}
          </section>
        ))}
      </div>
    </article>
  );
}

export default function PressReviews({ onOpenChat, onLogout, disabled }) {
  const [reviews, setReviews] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const heading = useRef(null);

  useEffect(() => {
    heading.current?.focus();
    const controller = new AbortController();
    async function load() {
      try {
        const saved = await listReviews({ signal: controller.signal });
        if (!controller.signal.aborted) setReviews(saved);
      } catch (cause) {
        if (controller.signal.aborted) return;
        if (cause.status === 401) onLogout();
        else setError(cause.message);
      } finally {
        if (!controller.signal.aborted) setIsLoading(false);
      }
    }
    load();
    return () => controller.abort();
  }, [onLogout, attempt]);

  return (
    <div className={styles.reviews}>
      <h1 ref={heading} tabIndex={-1}>Revues de presse</h1>
      <p className={styles.introduction}>Retrouvez les revues générées dans toutes vos discussions.</p>
      {isLoading ? <p role="status">Chargement des revues de presse…</p> : error ? (
        <div role="alert" className={styles.error}>
          <p>{error}</p>
          <button type="button" onClick={() => { setError(""); setIsLoading(true); setAttempt(attempt + 1); }}>Réessayer</button>
        </div>
      ) : reviews.length ? reviews.map((review) => (
        <ReviewCard key={review.id} review={review} onOpenChat={onOpenChat} disabled={disabled} />
      )) : <p className={styles.empty}>Aucune revue pour le moment. Ouvrez une discussion, puis cliquez sur « Générer la revue de presse ».</p>}
    </div>
  );
}
