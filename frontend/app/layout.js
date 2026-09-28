import './globals.css';
import Sidebar from '../components/Sidebar';

export const metadata = {
  title: 'Casefile - adaptive web app auditor',
  description: 'Point Casefile at a running app, get back an evidence-backed bug report and ready-to-paste fix prompts.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <Sidebar />
          <main className="main">{children}</main>
        </div>
      </body>
    </html>
  );
}
