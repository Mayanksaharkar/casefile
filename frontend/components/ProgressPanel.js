export default function ProgressPanel({ audit }) {
  const { phase, progress, log, budget } = audit;

  return (
    <div className="progress-panel">
      <div className="phase">{phase}</div>
      <div className="summary-strip" style={{ margin: '0 0 1rem' }}>
        <div className="stat">
          <b>{progress.pagesDiscovered}</b>
          <span>pages found</span>
        </div>
        <div className="stat">
          <b>
            {progress.actionsExecuted}/{budget}
          </b>
          <span>actions run</span>
        </div>
        <div className="stat">
          <b>{progress.statesVisited}</b>
          <span>states visited</span>
        </div>
        <div className="stat">
          <b>{progress.skippedDangerous}</b>
          <span>skipped (safe mode)</span>
        </div>
      </div>
      <div className="progress-log">
        {log
          .slice(-40)
          .slice()
          .reverse()
          .map((entry, i) => (
            <div key={i}>
              {new Date(entry.at).toLocaleTimeString()} — {entry.message}
            </div>
          ))}
      </div>
    </div>
  );
}
