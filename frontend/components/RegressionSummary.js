export default function RegressionSummary({ regression }) {
  if (!regression) return null;

  return (
    <div className="card regression-summary">
      <h3 style={{ marginBottom: '0.5rem' }}>Regression vs previous run</h3>
      <div className="summary-strip" style={{ margin: '0 0 1rem' }}>
        <div className="stat">
          <b>{regression.resolvedCount}</b>
          <span>resolved</span>
        </div>
        <div className="stat">
          <b>{regression.stillPresentCount}</b>
          <span>still open</span>
        </div>
        <div className="stat">
          <b>{regression.newCount}</b>
          <span>new</span>
        </div>
      </div>
      {regression.resolved.length > 0 && (
        <>
          <h4>Resolved since {new Date(regression.previousStartedAt).toLocaleString()}</h4>
          <ul className="resolved-list">
            {regression.resolved.map((r) => (
              <li key={r.id}>
                <span className="severity-tag" style={{ background: '#5b7065' }}>
                  {r.severity}
                </span>
                {r.title}
                <span className="issue-route" style={{ margin: 0 }}>
                  {r.route}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
