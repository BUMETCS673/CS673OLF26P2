import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { createDecksApi } from './api/decks';
import { createDemoRequest } from './api/decks.demo';
import DeckListPage from './pages/DeckListPage';
import DeckDetailPage from './pages/DeckDetailPage';
import './ws4.css';

// TODO(WS3): replace this temporary preview shell with AuthContext and App routes.
// Pages accept api/navigation props, so WS3 can connect them without demo imports.
const api = createDecksApi(createDemoRequest({
  getItem: (key) => window.localStorage.getItem(key),
  setItem: (key, value) => window.localStorage.setItem(key, value),
}));

function DemoApp() {
  const [route, setRoute] = useState(window.location.hash || '#/decks');
  const [newDeckId, setNewDeckId] = useState(null);
  useEffect(() => {
    const update = () => setRoute(window.location.hash || '#/decks');
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const match = route.match(/^#\/decks\/(\d+)$/);
  const showList = () => { setNewDeckId(null); window.location.hash = '/decks'; };
  return <div className="ws4">
    <header className="app-header"><a className="brand" href="#/decks"><span className="brand-mark" aria-hidden="true">c.</span>cadence<span className="brand-dot">.</span></a>
      <nav aria-label="Main navigation"><a href="#/decks" aria-current={!match ? 'page' : undefined}>My decks</a></nav>
      <span className="workspace-label">A space to remember</span></header>
    <aside className="demo-banner"><span className="demo-badge">Demo preview</span><span>Saved in this browser only. Account login and syncing are coming with team integration.</span></aside>
    {match ? <DeckDetailPage key={match[1]} api={api} deckId={match[1]} startAdding={String(newDeckId) === match[1]} onBack={showList} />
      : route === '#/decks' || route === '#' ? <DeckListPage api={api}
        onOpenDeck={(id) => { setNewDeckId(null); window.location.hash = `/decks/${id}`; }}
        onDeckCreated={(id) => { setNewDeckId(id); window.location.hash = `/decks/${id}`; }} />
      : <main className="ws4-page"><h1>Page not found</h1><button className="button primary" onClick={showList}>Back to decks</button></main>}
    <footer className="app-footer"><span>Small cards. Lasting knowledge.</span><span>Cadence · Your learning library</span></footer>
  </div>;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <DemoApp />
  </React.StrictMode>
);
