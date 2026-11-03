import { useLocation, useNavigate } from 'react-router-dom';
import { useSuggestions } from '../suggestions/SuggestionsContext.jsx';
import '../problemCards.css';

const cards = (count) => `${count} ${count === 1 ? 'card' : 'cards'}`;

/** The live notice when suggestions arrive. Waits while the learner is studying or reviewing. */
export default function SuggestionsNotice() {
  const { notice, ready, studying, dismissNotice } = useSuggestions();
  const { pathname } = useLocation();
  const navigate = useNavigate();

  const stillReady = notice && ready.some((item) => item.review_id === notice.review_id);
  if (!stillReady || studying || pathname.endsWith('/problem-cards')) return null;

  return <aside className="problem-cards-notice" role="status">
    <p><strong>{notice.deck_name}:</strong> I have suggestions for the {cards(notice.card_count)} you
      keep forgetting.</p>
    <div className="problem-cards-notice-actions">
      <button type="button" className="button primary" onClick={() => {
        dismissNotice();
        navigate(`/decks/${notice.deck_id}/problem-cards`);
      }}>See suggestions</button>
      <button type="button" className="button secondary" onClick={dismissNotice}>Close</button>
    </div>
  </aside>;
}
