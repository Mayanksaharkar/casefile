import { liveScreenshotUrl } from '../lib/api';

export default function LiveView({ audit, connected }) {
  const action = audit.currentAction;
  const hasShot = audit.liveViewVersion > 0;

  return (
    <div className="live-view">
      <div className="live-view-head">
        <span className={`live-dot${connected ? '' : ' stale'}`} />
        <span>{connected ? 'LIVE' : 'RECONNECTING'}</span>
        {action && (
          <span className="live-action">
            {action.kind === 'form' ? 'Filling in' : 'Clicking'} &ldquo;{action.label}&rdquo; on {action.pageUrl}
          </span>
        )}
      </div>
      {hasShot ? (
        <img
          className="live-view-shot"
          src={liveScreenshotUrl(audit.id, audit.liveViewVersion)}
          alt="Live view of the browser Casefile is driving"
        />
      ) : (
        <div className="live-view-placeholder">Waiting for the first screenshot…</div>
      )}
    </div>
  );
}
