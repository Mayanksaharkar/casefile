"use client";
import AuditForm from '../components/AuditForm';
import { motion } from 'framer-motion';
import { ShieldAlert } from 'lucide-react';

export default function DashboardPage() {
  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }} 
      transition={{ duration: 0.5 }}
      style={{ maxWidth: '800px', margin: '0 auto' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
        <motion.div
          initial={{ rotate: -90, scale: 0 }}
          animate={{ rotate: 0, scale: 1 }}
          transition={{ type: 'spring', stiffness: 200, delay: 0.2 }}
        >
          <ShieldAlert size={40} color="var(--brand)" />
        </motion.div>
        <h2 style={{ fontSize: '2.5rem', fontWeight: 800, margin: 0, background: 'linear-gradient(to right, #fff, var(--text-secondary))', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
          CASEFILE 
          <span style={{ fontSize: '1rem', verticalAlign: 'top', marginLeft: '0.5rem', color: 'var(--brand)', WebkitTextFillColor: 'var(--brand)' }}>v2.0</span>
        </h2>
      </div>
      
      <p style={{ color: 'var(--text-secondary)', fontSize: '1.1rem', lineHeight: 1.6, marginBottom: '2.5rem' }}>
        Deploy the adaptive auditor. Casefile maps the architecture, exercises real workflows, intercepts network layers, and generates strict, deterministic test vectors for your application.
      </p>
      
      <AuditForm />
    </motion.div>
  );
}
