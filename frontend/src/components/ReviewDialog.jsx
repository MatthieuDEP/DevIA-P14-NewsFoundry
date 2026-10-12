import { useEffect, useRef, useState } from "react";
import styles from "./PressReviews.module.css";

export default function ReviewDialog({ onClose, onGenerate, isGenerating }) {
  const dialog = useRef(null);
  const input = useRef(null);
  const [topic, setTopic] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!dialog.current.open) dialog.current.showModal();
    input.current?.focus();
  }, []);

  async function submit(event) {
    event.preventDefault();
    if (isGenerating || topic.trim().length < 2) return;
    setError("");
    try {
      await onGenerate(topic.trim());
    } catch (cause) {
      setError(cause.message);
    }
  }

  return (
    <dialog ref={dialog} className={styles.dialog} aria-labelledby="review-dialog-title" aria-describedby="review-dialog-description" onClose={onClose} onCancel={(event) => { if (isGenerating) event.preventDefault(); }}>
      <button className={styles.close} type="button" onClick={() => dialog.current.close()} disabled={isGenerating}>Fermer</button>
      <h2 id="review-dialog-title">Générer une revue de presse</h2>
      <p id="review-dialog-description">Choisissez un sujet abordé dans cette discussion.</p>
      <form onSubmit={submit} aria-busy={isGenerating}>
        <label htmlFor="review-topic">Thème de la revue de presse</label>
        <input ref={input} id="review-topic" value={topic} onChange={(event) => setTopic(event.target.value)} minLength={2} maxLength={200} disabled={isGenerating} required aria-describedby={error ? "review-error" : undefined} />
        {error && <p id="review-error" className={styles.error} role="alert">{error}</p>}
        {isGenerating && <p className={styles.status} role="status">Génération de votre revue de presse en cours…</p>}
        <button className={styles.generate} type="submit" disabled={isGenerating || topic.trim().length < 2}>
          {isGenerating ? "Génération…" : "Générer"}
        </button>
      </form>
    </dialog>
  );
}
