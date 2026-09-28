export default function GuidePage() {
  return (
    <div className="prose" style={{ maxWidth: '800px', lineHeight: '1.6' }}>
      <h2 className="eyebrow-free-title">How to Audit a Local App with Casefile</h2>
      <p className="subtitle">
        With the production-ready engine complete, Casefile autonomously handles performance, security, accessibility, API, and visual testing across multiple viewports. Here is how to use it against a local app.
      </p>

      <h3 style={{ marginTop: '2rem', marginBottom: '1rem', fontSize: '1.25rem', fontWeight: '600' }}>Step 1: Prepare Your Target App</h3>
      <ol style={{ paddingLeft: '1.5rem', marginBottom: '1.5rem' }}>
        <li style={{ marginBottom: '0.5rem' }}><strong>Start your app:</strong> Run the app you want to test on a local port (e.g., <code>http://localhost:3005</code>).</li>
        <li style={{ marginBottom: '0.5rem' }}><strong>(Optional) Add AI Context:</strong> In your target app's root folder, create a <code>.audit/cursor-context.md</code> file. Drop any recent architectural decisions or context here. Casefile will read this and inject it into the fix prompts so your AI assistant knows the context when fixing bugs.</li>
        <li style={{ marginBottom: '0.5rem' }}><strong>(Optional) Set up Schedules:</strong> Create an <code>.audit/schedules.yaml</code> if you want this app audited nightly.</li>
      </ol>

      <h3 style={{ marginTop: '2rem', marginBottom: '1rem', fontSize: '1.25rem', fontWeight: '600' }}>Step 2: Trigger the Audit</h3>
      <ul style={{ paddingLeft: '1.5rem', marginBottom: '1.5rem' }}>
        <li style={{ marginBottom: '0.5rem' }}>Click <strong>"New audit"</strong> in the sidebar.</li>
        <li style={{ marginBottom: '0.5rem' }}>Enter the URL of your local app (e.g., <code>http://localhost:3005</code>).</li>
        <li style={{ marginBottom: '0.5rem' }}>You can also specify a budget (how many actions the AI should take) and a repository path (so Casefile knows where to find your config files).</li>
      </ul>

      <h4 style={{ marginTop: '1.5rem', marginBottom: '0.75rem', fontSize: '1.1rem', fontWeight: '600' }}>What Happens Automatically:</h4>
      <p style={{ marginBottom: '1rem' }}>Once you hit start, you don't need to configure anything else. Casefile will automatically:</p>
      <ul style={{ paddingLeft: '1.5rem', marginBottom: '1.5rem' }}>
        <li><strong>Loop Viewports:</strong> Run passes in Desktop, Tablet, and Mobile resolutions.</li>
        <li><strong>Probe Security:</strong> Inject XSS payloads into forms and check cookie flags.</li>
        <li><strong>Monitor APIs:</strong> Track all <code>fetch</code> and <code>xhr</code> calls to catch 500s or 401s in the background.</li>
        <li><strong>Test Web Vitals:</strong> Measure LCP, CLS, INP, and TTFB as it explores.</li>
        <li><strong>Check Accessibility:</strong> Verify keyboard focus boundaries and ARIA labels.</li>
      </ul>

      <h3 style={{ marginTop: '2rem', marginBottom: '1rem', fontSize: '1.25rem', fontWeight: '600' }}>Step 3: Review the Definitive Report</h3>
      <p style={{ marginBottom: '1rem' }}>Once the audit finishes, click to view the <strong>HTML Report</strong>.</p>
      <ul style={{ paddingLeft: '1.5rem', marginBottom: '1.5rem' }}>
        <li>It is a fully self-contained HTML file (you can share it on Slack or email it).</li>
        <li>It will highlight regressions against baseline images.</li>
        <li><strong>Rich Fix Prompts:</strong> Every issue will have a <strong>"Copy Fix Prompt"</strong> button. This copies a massive context block (containing the DOM snapshot, HAR network logs, before/after images, and your cursor context).</li>
      </ul>

      <h3 style={{ marginTop: '2rem', marginBottom: '1rem', fontSize: '1.25rem', fontWeight: '600' }}>Step 4: Fix in One Shot</h3>
      <p style={{ marginBottom: '1.5rem' }}>
        Go to your IDE (like Cursor or Windsurf) and paste the copied Fix Prompt into the chat. Because the prompt contains the exact error, the visual context, and the API failure traces, your IDE will be able to fix the bug in a single shot without you needing to explain what went wrong.
      </p>
    </div>
  );
}
