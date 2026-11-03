import { useSuggestions } from '../suggestions/SuggestionsContext.jsx';
import '../leech.css';

/**
 * The deck page's notice that suggestions are ready for this deck.
 *
 * props:
 *   deckId    string, from the route
 *   onReview  () => void, opens the review page
 */
export default function LeechBanner({ deckId, onReview }) {
  const { ready } = useSuggestions();
  const suggestion = ready.find((item) => String(item.deck_id) === String(deckId));
  if (!suggestion) return null;

  const count = suggestion.card_count;
  return <section className="panel leech-banner">
    <p>You keep forgetting {count} {count === 1 ? 'card' : 'cards'}. I have some suggestions.</p>
    <button type="button" className="button primary" onClick={onReview}>See suggestions</button>
  </section>;
}
