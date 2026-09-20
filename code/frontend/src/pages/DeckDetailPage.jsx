/**
 * WS4 (Nurzat) owns this file.
 *
 * Placeholder so `/decks/:id` has something to render — see DeckListPage.jsx.
 * `useParams()` is where the deck id comes from.
 */

import { useParams } from "react-router-dom";

export default function DeckDetailPage() {
  const { id } = useParams();

  return (
    <main className="page">
      <h1>Deck {id}</h1>
      <p className="page-status">Coming in WS4.</p>
    </main>
  );
}
