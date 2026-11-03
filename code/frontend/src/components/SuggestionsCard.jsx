import { useSuggestions } from '../suggestions/SuggestionsContext.jsx';
import '../leech.css';

/**
 * The home page's list of ready suggestions, across all decks.
 *
 * props:
 *   onReview  (deckId) => void, opens that deck's review page
 */
export default function SuggestionsCard({ onReview }) {
  const { ready } = useSuggestions();
  if (ready.length === 0) return null;

  return <section className="panel leech-home" aria-labelledby="suggestions-heading">
    <h2 id="suggestions-heading">Suggestions for you</h2>
    <ul>
      {ready.map((item) => <li key={item.review_id}>
        <span>{item.deck_name}: {item.card_count} {item.card_count === 1 ? 'card' : 'cards'}</span>
        <button type="button" className="button secondary"
          aria-label={`Review suggestions for ${item.deck_name}`}
          onClick={() => onReview(item.deck_id)}>Review</button>
      </li>)}
    </ul>
  </section>;
}
