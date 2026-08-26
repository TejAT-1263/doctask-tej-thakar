import { useState, useEffect, useCallback, useRef } from 'react'
import { api } from './api.js'

// ─── Design tokens ──────────────────────────────────────────────────────────────
const c = {
  bg:           '#fbfaf6',
  surface:      '#ffffff',
  border:       '#e5e0d8',
  borderLight:  '#eeeae4',
  text:         '#1c1917',
  textMuted:    '#78716c',
  textFaint:    '#a8a29e',
  primary:      '#1d4ed8',
  primaryLight: '#eff6ff',
  success:      '#15803d',
  successLight: '#f0fdf4',
  warning:      '#b45309',
  warningLight: '#fffbeb',
  danger:       '#b91c1c',
  dangerLight:  '#fef2f2',
  tagBg:        '#f5f2ec',
}
const font = {
  heading: "'Plus Jakarta Sans', -apple-system, sans-serif",
  body:    "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
  mono:    "'Menlo', 'Fira Code', 'Consolas', monospace",
}
const s = {
  app:       { maxWidth: 1160, margin: '0 auto', padding: '36px 24px 72px', fontFamily: font.body },
  card:      { background: c.surface, borderRadius: 14, padding: '32px', border: `1px solid ${c.border}`, boxShadow: '0 1px 6px rgba(0,0,0,.05)', marginBottom: 20 },
  infoBox:   { background: c.bg, borderRadius: 10, padding: '14px 18px', border: `1px solid ${c.borderLight}` },
  btn:       { padding: '9px 20px', borderRadius: 8, border: 'none', cursor: 'pointer', fontSize: 14, fontWeight: 500, fontFamily: font.body, lineHeight: 1, transition: 'opacity .15s' },
  btnPrimary:{ background: c.primary, color: '#fff' },
  btnSuccess:{ background: c.success, color: '#fff' },
  btnDanger: { background: c.danger,  color: '#fff' },
  btnGhost:  { background: c.tagBg,   color: c.text, border: `1px solid ${c.border}` },
  pill:      { display: 'inline-block', padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.3px' },
  badge:     { display: 'inline-block', padding: '3px 10px', borderRadius: 99, fontSize: 12, fontWeight: 600 },
  input:     { width: '100%', padding: '9px 13px', borderRadius: 8, border: `1px solid ${c.border}`, fontSize: 14, outline: 'none', background: c.surface, color: c.text, fontFamily: font.body },
  textarea:  { width: '100%', padding: '11px 13px', borderRadius: 8, border: `1px solid ${c.border}`, fontSize: 14, outline: 'none', minHeight: 110, resize: 'vertical', background: c.surface, color: c.text, fontFamily: font.body, lineHeight: 1.6 },
  log:       { background: '#1a1917', color: '#e7e5e4', borderRadius: 10, padding: 18, fontFamily: font.mono, fontSize: 12, maxHeight: 340, overflowY: 'auto', lineHeight: 1.9 },
  table:     { width: '100%', fontSize: 13, borderCollapse: 'collapse' },
  th:        { textAlign: 'left', padding: '10px 14px', color: c.textMuted, fontWeight: 600, borderBottom: `1px solid ${c.border}`, fontSize: 11, textTransform: 'uppercase', letterSpacing: '.6px' },
  td:        { padding: '10px 14px', borderBottom: `1px solid ${c.borderLight}`, verticalAlign: 'top', color: c.text },
}

// ─── Color maps ─────────────────────────────────────────────────────────────────
const statusColor  = { pending:'#d97706', running:'#1d4ed8', paused_hitl:'#b91c1c', completed:'#15803d', failed:'#b91c1c', cancelled:'#78716c' }
const conflictTypeColor = { FACTUAL:{bg:'#fff7ed',color:'#c2410c'}, TEMPORAL:{bg:'#f0fdf4',color:'#166534'}, DEFINITIONAL:{bg:'#eff6ff',color:'#1d4ed8'}, OMISSION:{bg:'#faf5ff',color:'#7e22ce'} }
const confidenceColor   = { HIGH:{bg:'#fef2f2',color:'#b91c1c'}, MEDIUM:{bg:'#fffbeb',color:'#b45309'}, LOW:{bg:'#eff6ff',color:'#1d4ed8'} }
const dispositionColor  = { APPROVE:{bg:'#f0fdf4',color:'#15803d',border:'#bbf7d0'}, DENY:{bg:'#fef2f2',color:'#b91c1c',border:'#fecaca'}, REQUEST_MORE_INFO:{bg:'#fffbeb',color:'#b45309',border:'#fde68a'} }
const severityBorder    = { high: c.danger, medium: '#d97706', low: c.primary, info: c.textFaint, critical: c.danger, warning: '#d97706' }

// ─── Tiny helpers ───────────────────────────────────────────────────────────────
const Badge        = ({ status }) => { const col = statusColor[status] || '#78716c'; return <span style={{ ...s.badge, background: col+'18', color: col }}>{status?.replace(/_/g,' ').toUpperCase()}</span> }
const TypePill     = ({ type }) => { const col = conflictTypeColor[type] || {bg:c.tagBg,color:c.textMuted}; return <span style={{ ...s.pill, background:col.bg, color:col.color }}>{type||'—'}</span> }
const ConfPill     = ({ v }) => { const col = confidenceColor[v] || {bg:c.tagBg,color:c.textMuted}; return <span style={{ ...s.pill, background:col.bg, color:col.color }}>{v}</span> }
const SevPill      = ({ v }) => { const map={high:{bg:'#fef2f2',color:'#b91c1c'},medium:{bg:'#fffbeb',color:'#b45309'},low:{bg:'#eff6ff',color:'#1d4ed8'},info:{bg:c.tagBg,color:c.textMuted},critical:{bg:'#fef2f2',color:'#b91c1c'},warning:{bg:'#fffbeb',color:'#b45309'}}; const col=map[v?.toLowerCase()]||{bg:c.tagBg,color:c.textMuted}; return <span style={{ ...s.pill, background:col.bg, color:col.color }}>{v}</span> }

// ─── Pipeline stepper ───────────────────────────────────────────────────────────
const PIPELINE_STEPS = [
  { id: 'upload',    label: 'Upload',       icon: '📤' },
  { id: 'stage1',    label: 'Stage 1',      icon: '🔍', sub: 'Classify · Extract · Signals · Reconcile' },
  { id: 'review1',   label: 'Review Gate 1',icon: '👁', sub: 'Human review of report & conflicts' },
  { id: 'stage2',    label: 'Stage 2',      icon: '📋', sub: 'Rule check · Recommendation' },
  { id: 'review2',   label: 'Review Gate 2',icon: '👁', sub: 'Human review of findings' },
  { id: 'complete',  label: 'Complete',     icon: '✅' },
]

function getStepIndex(status, stage, node) {
  if (!status) return 0
  if (status === 'pending') return 0
  if (status === 'completed') return 5
  if (status === 'failed') return -1
  if (status === 'paused_hitl') return stage === 1 ? 2 : 4
  if (status === 'running') return stage === 1 ? 1 : 3
  return 0
}

function PipelineStepper({ status, stage, node }) {
  const current = getStepIndex(status, stage, node)
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 32, overflowX: 'auto', paddingBottom: 4 }}>
      {PIPELINE_STEPS.map((step, i) => {
        const done    = i < current
        const active  = i === current
        const pending = i > current
        const color   = done ? c.success : active ? c.primary : c.textFaint
        return (
          <div key={step.id} style={{ display: 'flex', alignItems: 'center', flex: i < PIPELINE_STEPS.length - 1 ? 1 : 'none', minWidth: 0 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
              {/* Circle */}
              <div style={{
                width: 36, height: 36, borderRadius: '50%',
                background: done ? c.successLight : active ? c.primaryLight : c.bg,
                border: `2px solid ${color}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 16, transition: 'all .3s',
              }}>
                {done ? '✓' : step.icon}
              </div>
              {/* Labels */}
              <div style={{ marginTop: 6, textAlign: 'center', width: 88 }}>
                <div style={{ fontSize: 11, fontWeight: active ? 700 : 500, color, whiteSpace: 'nowrap' }}>{step.label}</div>
                {step.sub && active && (
                  <div style={{ fontSize: 10, color: c.textFaint, marginTop: 2, lineHeight: 1.4, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{step.sub}</div>
                )}
              </div>
            </div>
            {/* Connector */}
            {i < PIPELINE_STEPS.length - 1 && (
              <div style={{ flex: 1, height: 2, background: done ? c.success : c.borderLight, marginBottom: 22, marginLeft: 4, marginRight: 4, minWidth: 16, transition: 'background .3s' }} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Caution summary banner ──────────────────────────────────────────────────────
function CautionBanner({ items, report }) {
  const highConflicts  = report?.conflicts?.filter(c => c.severity === 'high')?.length || 0
  const highSignals    = report?.fraud_signals?.filter(s => s.confidence === 'HIGH')?.length || 0
  const paradoxes      = report?.timeline_events?.filter(e => e.is_paradox)?.length || 0
  const unverified     = items.filter(i => i.status === 'pending' && i.item_type !== 'report_section').length

  if (!highConflicts && !highSignals && !paradoxes) return null

  return (
    <div style={{
      background: '#fff7ed', border: '1.5px solid #fb923c',
      borderRadius: 12, padding: '16px 20px', marginBottom: 24,
    }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <span style={{ fontSize: 20, flexShrink: 0 }}>⚠️</span>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14, color: '#c2410c', marginBottom: 6 }}>
            Review these before approving
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {highConflicts > 0 && <span style={{ fontSize: 13, color: '#9a3412' }}>🔴 <strong>{highConflicts}</strong> high-severity conflict{highConflicts>1?'s':''}</span>}
            {highSignals > 0   && <span style={{ fontSize: 13, color: '#9a3412' }}>🔴 <strong>{highSignals}</strong> HIGH-confidence fraud signal{highSignals>1?'s':''}</span>}
            {paradoxes > 0     && <span style={{ fontSize: 13, color: '#9a3412' }}>⏱ <strong>{paradoxes}</strong> temporal paradox{paradoxes>1?'es':''}</span>}
          </div>
          <div style={{ fontSize: 12, color: '#c2410c', marginTop: 8, opacity: .85 }}>
            Check the Analysis tab for full details before proceeding.
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Read-gated review item ──────────────────────────────────────────────────────
// • Body is hidden until user clicks "Expand to Read"
// • Approve button only appears after body is expanded
// • HIGH severity items require an "I acknowledge" checkbox before approve
function ReviewItem({ item, report, onDecide }) {
  const [expanded,     setExpanded]     = useState(false)
  const [acknowledged, setAcknowledged] = useState(false)
  const [note,         setNote]         = useState('')
  const [deciding,     setDeciding]     = useState(false)
  const bodyRef = useRef(null)

  // Determine severity from item type + linked data
  const isHighRisk = (() => {
    if (item.item_type === 'conflict') {
      const match = report?.conflicts?.find(conf =>
        item.title.toLowerCase().includes(conf.field?.toLowerCase()) ||
        item.body?.includes(conf.doc_a_id)
      )
      return match?.severity === 'high'
    }
    if (item.item_type === 'finding') {
      return item.title?.toLowerCase().includes('[critical]') || item.title?.toLowerCase().includes('[high]')
    }
    return false
  })()

  const borderColor = item.status === 'approved' ? c.success
    : item.status === 'rejected'  ? c.danger
    : isHighRisk ? c.danger : '#d97706'

  const canApprove = expanded && (!isHighRisk || acknowledged)

  const decide = async (approved) => {
    setDeciding(true)
    await onDecide(item.id, approved, note)
    setDeciding(false)
  }

  const typeIcon = { conflict: '⚡', finding: '📋', report_section: '📄' }[item.item_type] || '•'

  return (
    <div style={{
      border: `1px solid ${c.border}`,
      borderLeft: `4px solid ${borderColor}`,
      borderRadius: 10, marginBottom: 14,
      background: item.status !== 'pending' ? c.bg : c.surface,
      overflow: 'hidden',
    }}>
      {/* Header row */}
      <div style={{ padding: '14px 18px', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <span style={{ fontSize: 16, flexShrink: 0, marginTop: 1 }}>{typeIcon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: c.text, lineHeight: 1.4, marginBottom: 4 }}>
            {item.title}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: c.textFaint }}>Stage {item.stage}</span>
            <span style={{ fontSize: 11, color: c.textFaint }}>·</span>
            <span style={{ fontSize: 11, color: c.textFaint, textTransform: 'capitalize' }}>{item.item_type.replace('_',' ')}</span>
            {isHighRisk && item.status === 'pending' && (
              <span style={{ ...s.pill, background: '#fef2f2', color: c.danger }}>HIGH RISK</span>
            )}
            <Badge status={item.status} />
          </div>
        </div>

        {/* Expand / collapse toggle */}
        {item.status === 'pending' && (
          <button
            onClick={() => setExpanded(v => !v)}
            style={{
              ...s.btn, ...s.btnGhost,
              padding: '6px 14px', fontSize: 12, flexShrink: 0,
              background: expanded ? c.primaryLight : c.tagBg,
              color: expanded ? c.primary : c.textMuted,
              border: `1px solid ${expanded ? c.primary : c.border}`,
            }}
          >
            {expanded ? '▲ Collapse' : '▼ Expand to Read'}
          </button>
        )}
      </div>

      {/* Body — only visible after expanding (or if already decided) */}
      {(expanded || item.status !== 'pending') && (
        <div style={{ borderTop: `1px solid ${c.borderLight}`, padding: '14px 18px 0' }}>
          <div
            ref={bodyRef}
            style={{
              background: c.bg, borderRadius: 8, padding: '12px 16px',
              fontFamily: item.item_type === 'report_section' ? font.body : font.mono,
              fontSize: item.item_type === 'report_section' ? 13 : 12,
              color: c.text,
              whiteSpace: item.item_type === 'report_section' ? 'normal' : 'pre-wrap',
              lineHeight: 1.7,
              maxHeight: item.item_type === 'report_section' ? 480 : 260,
              overflowY: 'auto', marginBottom: 14,
            }}
            {...(item.item_type === 'report_section'
              ? { dangerouslySetInnerHTML: { __html: item.body } }
              : { children: item.body }
            )}
          />

          {/* HIGH-risk acknowledgement checkbox */}
          {isHighRisk && item.status === 'pending' && (
            <label style={{
              display: 'flex', gap: 10, alignItems: 'flex-start',
              background: '#fef2f2', border: '1px solid #fecaca',
              borderRadius: 8, padding: '10px 14px', marginBottom: 14,
              cursor: 'pointer', fontSize: 13, color: c.danger, lineHeight: 1.5,
            }}>
              <input
                type="checkbox"
                checked={acknowledged}
                onChange={e => setAcknowledged(e.target.checked)}
                style={{ marginTop: 2, flexShrink: 0, accentColor: c.danger }}
              />
              <span>
                <strong>I have reviewed this high-risk item</strong> and understand that approving it
                does not resolve the underlying issue — it only records my acknowledgement.
                The final determination must be made by a licensed adjuster.
              </span>
            </label>
          )}

          {/* Reviewer note + action buttons */}
          {item.status === 'pending' && (
            <div style={{ paddingBottom: 14 }}>
              <input
                placeholder="Reviewer note (optional but recommended for high-risk items)"
                style={{ ...s.input, marginBottom: 10, fontSize: 13 }}
                value={note}
                onChange={e => setNote(e.target.value)}
              />
              <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <button
                  style={{
                    ...s.btn, ...s.btnSuccess,
                    opacity: canApprove ? 1 : 0.35,
                    cursor: canApprove ? 'pointer' : 'not-allowed',
                  }}
                  onClick={() => canApprove && !deciding && decide(true)}
                  title={!expanded ? 'Expand and read before approving' : isHighRisk && !acknowledged ? 'Acknowledge the risk above before approving' : ''}
                >
                  {deciding ? 'Saving…' : '✓ Approve'}
                </button>
                <button
                  style={{ ...s.btn, ...s.btnDanger, opacity: expanded ? 1 : 0.35, cursor: expanded ? 'pointer' : 'not-allowed' }}
                  onClick={() => expanded && !deciding && decide(false)}
                >
                  ✗ Reject
                </button>
                {!canApprove && (
                  <span style={{ fontSize: 12, color: c.textMuted }}>
                    {!expanded ? '← Expand to read first' : '← Check the acknowledgement above'}
                  </span>
                )}
              </div>
            </div>
          )}

          {item.reviewer_note && item.status !== 'pending' && (
            <div style={{ paddingBottom: 14, fontSize: 12, color: c.textMuted, fontStyle: 'italic' }}>
              Note: {item.reviewer_note}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Review tab ─────────────────────────────────────────────────────────────────
function ReviewTab({ items, report, onDecide, onResume, runStatus, currentStage }) {
  const pending  = items.filter(i => i.status === 'pending')
  const decided  = items.filter(i => i.status !== 'pending')

  // Sort: high-risk pending first, then other pending, then decided
  const sortedPending = [...pending].sort((a, b) => {
    const aHigh = a.item_type === 'conflict' && a.title?.toLowerCase().includes('high')
    const bHigh = b.item_type === 'conflict' && b.title?.toLowerCase().includes('high')
    return bHigh - aHigh
  })

  const allPendingDecided = pending.length === 0 && items.length > 0

  return (
    <div>
      {/* Progress summary */}
      {items.length > 0 && (
        <div style={{ display: 'flex', gap: 14, marginBottom: 22, flexWrap: 'wrap' }}>
          {[
            { label: 'Total Items',  value: items.length,   color: c.text },
            { label: 'Pending',      value: pending.length, color: '#d97706' },
            { label: 'Approved',     value: items.filter(i=>i.status==='approved').length, color: c.success },
            { label: 'Rejected',     value: items.filter(i=>i.status==='rejected').length, color: c.danger },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ ...s.infoBox, textAlign: 'center', minWidth: 90 }}>
              <div style={{ fontSize: 22, fontWeight: 800, color, fontFamily: font.heading, lineHeight: 1 }}>{value}</div>
              <div style={{ fontSize: 11, color: c.textFaint, marginTop: 4 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {items.length === 0 && (
        <div style={{ ...s.infoBox, color: c.textMuted, fontSize: 14 }}>
          No review items yet. They appear here after Stage 1 analysis completes.
        </div>
      )}

      {/* Pending items — priority-ordered */}
      {sortedPending.length > 0 && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '.7px', marginBottom: 10 }}>
            Pending ({sortedPending.length}) — Expand each item before deciding
          </div>
          {sortedPending.map(item => (
            <ReviewItem key={item.id} item={item} report={report} onDecide={onDecide} />
          ))}
        </div>
      )}

      {/* Decided items — collapsed by default */}
      {decided.length > 0 && (
        <div style={{ marginTop: sortedPending.length > 0 ? 24 : 0 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '.7px', marginBottom: 10 }}>
            Decided ({decided.length})
          </div>
          {decided.map(item => (
            <ReviewItem key={item.id} item={item} report={report} onDecide={onDecide} />
          ))}
        </div>
      )}

      {/* Resume gate */}
      {allPendingDecided && runStatus === 'paused_hitl' && (
        <div style={{
          background: c.successLight, border: `1.5px solid #bbf7d0`,
          borderRadius: 12, padding: '18px 22px', marginTop: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, color: c.success }}>All items decided — ready to continue</div>
            <div style={{ fontSize: 13, color: '#166534', marginTop: 4 }}>
              {items.filter(i=>i.status==='approved').length} approved · {items.filter(i=>i.status==='rejected').length} rejected
            </div>
          </div>
          <button style={{ ...s.btn, ...s.btnPrimary, fontSize: 14, padding: '11px 28px' }} onClick={onResume}>
            Resume Pipeline →
          </button>
        </div>
      )}
    </div>
  )
}

// ─── Analysis tab (report + conflicts + timeline + signals together) ─────────────
function AnalysisTab({ report }) {
  const [subTab, setSubTab] = useState('report')
  const conflicts  = report?.conflicts || []
  const signals    = report?.fraud_signals || []
  const timeline   = report?.timeline_events || []
  const paradoxes  = timeline.filter(e => e.is_paradox)

  const subTabs = [
    { id: 'report',    label: 'Report' },
    { id: 'conflicts', label: `Conflicts${conflicts.length ? ` (${conflicts.length})` : ''}` },
    { id: 'signals',   label: `Signals${signals.length ? ` (${signals.length})` : ''}` },
    { id: 'timeline',  label: `Timeline${paradoxes.length ? ` ⚠️${paradoxes.length}` : ''}` },
  ]

  return (
    <div>
      {/* Sub-tab bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 22, flexWrap: 'wrap' }}>
        {subTabs.map(st => (
          <button
            key={st.id}
            onClick={() => setSubTab(st.id)}
            style={{
              ...s.btn,
              background: subTab === st.id ? c.primary : c.tagBg,
              color: subTab === st.id ? '#fff' : c.textMuted,
              border: 'none', padding: '7px 16px', fontSize: 13,
            }}
          >
            {st.label}
          </button>
        ))}
      </div>

      {/* Report */}
      {subTab === 'report' && (
        <>
          {/* Stage 3 pending-approval banner ────────────────────────────────
              The addendum is staged in pending_stage3_addendum; it has NOT
              been merged into report_html yet.  The current report shown below
              is the last committed version.  The human must approve the update
              in the Review tab before it appears here.                        */}
          {report?.pending_stage3_addendum && (
            <div style={{
              background: '#fffbeb', border: '1.5px solid #fcd34d',
              borderRadius: 10, padding: '14px 18px', marginBottom: 16,
              display: 'flex', gap: 12, alignItems: 'flex-start',
            }}>
              <span style={{ fontSize: 20, flexShrink: 0 }}>⏳</span>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14, color: '#92400e', marginBottom: 4 }}>
                  Stage 3 update pending approval
                </div>
                <div style={{ fontSize: 13, color: '#78350f', lineHeight: 1.5 }}>
                  A new document has been processed and an addendum is staged for review.
                  The report below shows the <strong>last committed version</strong> —
                  the addendum will appear here only after a reviewer approves it in the&nbsp;
                  <strong>Review</strong> tab.
                  Rejecting the update discards it without changing this report.
                </div>
              </div>
            </div>
          )}
          {!report?.report_html
            ? <div style={{ ...s.infoBox, color: c.textMuted, fontSize: 14 }}>Report not yet generated.</div>
            : <>
                <style>{`
                  .conflict-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;text-transform:uppercase;margin-right:4px}
                  .conflict-factual{background:#fff7ed;color:#c2410c}.conflict-temporal{background:#f0fdf4;color:#166534}
                  .conflict-definitional{background:#eff6ff;color:#1d4ed8}.conflict-omission{background:#faf5ff;color:#7e22ce}
                  cite[data-doc-id]{font-style:normal;font-size:11px;background:#eff6ff;color:#1d4ed8;padding:1px 6px;border-radius:4px;cursor:help}
                `}</style>
                <div style={{ background: c.bg, borderRadius: 10, padding: 24, maxHeight: 560, overflowY: 'auto', border: `1px solid ${c.border}`, lineHeight: 1.7, fontSize: 14 }}
                  dangerouslySetInnerHTML={{ __html: report.report_html }} />
              </>
          }
        </>
      )}

      {/* Conflicts */}
      {subTab === 'conflicts' && (
        <div>
          {/* Intra-doc notice */}
          {conflicts.length > 0 && conflicts[0]?.doc_a_id === conflicts[0]?.doc_b_id && (
            <div style={{ background: c.primaryLight, border: `1px solid #bfdbfe`, borderRadius: 10, padding: '10px 16px', marginBottom: 16, fontSize: 13, color: c.primary, display: 'flex', gap: 10 }}>
              <span>ℹ️</span>
              <span><strong>Single-document analysis.</strong> These are internal inconsistencies found within the same document. Upload the policy schedule alongside the claim form to enable cross-document conflict detection.</span>
            </div>
          )}
          {/* Taxonomy summary */}
          {conflicts.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 22 }}>
              {['FACTUAL','TEMPORAL','DEFINITIONAL','OMISSION'].map(type => {
                const col   = conflictTypeColor[type]
                const count = conflicts.filter(c => c.conflict_type === type).length
                return (
                  <div key={type} style={{ background: col.bg, borderRadius: 10, padding: '14px', textAlign: 'center', border: `1px solid ${col.color}22` }}>
                    <div style={{ fontSize: 24, fontWeight: 800, color: col.color, fontFamily: font.heading }}>{count}</div>
                    <div style={{ fontSize: 11, color: col.color, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.5px', marginTop: 3 }}>{type}</div>
                  </div>
                )
              })}
            </div>
          )}
          {conflicts.length === 0
            ? (
              <div style={{ ...s.infoBox, lineHeight: 1.7 }}>
                <div style={{ fontWeight: 600, color: c.text, marginBottom: 6 }}>No conflicts detected</div>
                <div style={{ fontSize: 13, color: c.textMuted }}>
                  If you uploaded a single document, conflict detection checks for internal inconsistencies within that document.
                  To detect cross-document conflicts (e.g. claim form vs policy schedule), upload both files together in one run.
                </div>
              </div>
            )
            : conflicts.sort((a,b) => {
                const rank = {high:0,medium:1,low:2}
                return (rank[a.severity]||1) - (rank[b.severity]||1)
              }).map((conf, i) => {
                const isSameDoc = conf.doc_a_id === conf.doc_b_id
                return (
                  <div key={i} style={{
                    border: `1px solid ${c.border}`,
                    borderLeft: `4px solid ${severityBorder[conf.severity] || c.textFaint}`,
                    borderRadius: 10, padding: '16px 20px', marginBottom: 12, background: c.surface,
                  }}>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
                      <TypePill type={conf.conflict_type} />
                      <SevPill v={conf.severity} />
                      {isSameDoc && <span style={{ ...s.pill, background: c.primaryLight, color: c.primary }}>INTERNAL</span>}
                      <span style={{ fontSize: 13, fontWeight: 600, color: c.text }}>{conf.field}</span>
                    </div>
                    <p style={{ fontSize: 13, color: c.text, lineHeight: 1.6, margin: '0 0 12px 0' }}>{conf.description}</p>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <div style={{ background: '#fef2f2', borderRadius: 7, padding: '9px 13px', fontSize: 12, fontFamily: font.mono, color: c.danger }}>
                        {isSameDoc ? 'Section A' : `Doc A`}: {conf.value_a}
                      </div>
                      <div style={{ background: '#f0fdf4', borderRadius: 7, padding: '9px 13px', fontSize: 12, fontFamily: font.mono, color: c.success }}>
                        {isSameDoc ? 'Section B' : `Doc B`}: {conf.value_b}
                      </div>
                    </div>
                  </div>
                )
              })
          }
        </div>
      )}

      {/* Signals */}
      {subTab === 'signals' && (
        <div>
          <div style={{
            background: c.warningLight, border: `1px solid #fde68a`, borderRadius: 10,
            padding: '12px 16px', marginBottom: 20, fontSize: 13, color: c.warning,
            display: 'flex', gap: 10, lineHeight: 1.6,
          }}>
            <span style={{ flexShrink: 0 }}>⚠️</span>
            <span><strong>Patterns that warrant review, not accusations.</strong> Deterministic rule-based matching — no LLM involved. Requires holistic assessment by a qualified professional.</span>
          </div>
          {signals.length === 0
            ? (
              <div style={{ ...s.infoBox, lineHeight: 1.7 }}>
                <div style={{ fontWeight: 600, color: c.text, marginBottom: 6 }}>No signals detected</div>
                <div style={{ fontSize: 13, color: c.textMuted }}>
                  The rule-based detectors check for: temporal paradoxes (treatment before incident), short policy tenure (incident within 30 days of inception), late intimation (claim filed 30+ days after incident), and round claim amounts. None of these patterns matched the extracted facts.
                </div>
              </div>
            )
            : signals.sort((a,b) => { const r={HIGH:0,MEDIUM:1,LOW:2}; return (r[a.confidence]||1)-(r[b.confidence]||1) }).map((sig, i) => {
                const col = confidenceColor[sig.confidence] || {bg:c.tagBg,color:c.textMuted}
                return (
                  <div key={i} style={{ border:`1px solid ${c.border}`, borderLeft:`4px solid ${col.color}`, borderRadius:10, padding:'16px 20px', marginBottom:12, background:c.surface }}>
                    <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:10, flexWrap:'wrap' }}>
                      <ConfPill v={sig.confidence} />
                      <span style={{ fontWeight:600, fontSize:14, color:c.text }}>{sig.title}</span>
                      <span style={{ fontSize:11, color:c.textFaint, fontFamily:font.mono, marginLeft:'auto' }}>{sig.signal_id}</span>
                    </div>
                    <p style={{ fontSize:13, color:c.text, margin:'0 0 10px 0', lineHeight:1.6 }}>{sig.description}</p>
                    <div style={{ background:c.bg, borderRadius:7, padding:'9px 13px', fontSize:12, fontFamily:font.mono, color:c.textMuted }}>
                      {sig.evidence}
                    </div>
                    {sig.regulatory_ref && (
                      <div style={{ fontSize:12, color:c.textMuted, marginTop:8 }}>📋 {sig.regulatory_ref}</div>
                    )}
                  </div>
                )
              })
          }
        </div>
      )}

      {/* Timeline */}
      {subTab === 'timeline' && (
        <div>
          {paradoxes.length > 0 && (
            <div style={{ background:c.dangerLight, border:`1px solid #fecaca`, borderRadius:10, padding:'12px 16px', marginBottom:20, fontSize:13, color:c.danger, display:'flex', gap:10 }}>
              <span>⚠️</span>
              <span><strong>{paradoxes.length} temporal paradox{paradoxes.length>1?'es':''} detected.</strong> Review flagged events carefully.</span>
            </div>
          )}
          {!timeline.length
            ? <div style={{ ...s.infoBox, color:c.textMuted, fontSize:14 }}>No dated events found in documents.</div>
            : (
              <div style={{ position:'relative' }}>
                <div style={{ position:'absolute', left:19, top:8, bottom:0, width:2, background:c.border, zIndex:0 }} />
                {timeline.map((ev, i) => (
                  <div key={i} style={{ display:'flex', gap:20, marginBottom:20, position:'relative', zIndex:1 }}>
                    <div style={{ flexShrink:0, width:40, display:'flex', alignItems:'flex-start', justifyContent:'center', paddingTop:3 }}>
                      <div style={{ width:18, height:18, borderRadius:'50%', background:ev.is_paradox?c.danger:c.primary, border:'3px solid #fff', boxShadow:`0 0 0 2px ${ev.is_paradox?c.danger:c.primary}` }} />
                    </div>
                    <div style={{ flex:1 }}>
                      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:5, flexWrap:'wrap' }}>
                        <span style={{ fontWeight:600, fontSize:13, fontFamily:font.mono, color:c.text }}>{ev.date_iso||ev.date_raw}</span>
                        {ev.is_paradox && <span style={{ ...s.pill, background:c.dangerLight, color:c.danger }}>PARADOX</span>}
                      </div>
                      <div style={{ fontSize:14, color:c.text, lineHeight:1.5, marginBottom:5 }}>{ev.event}</div>
                      {ev.source_excerpt && (
                        <div style={{ fontSize:12, color:c.textMuted, fontStyle:'italic', background:c.bg, borderRadius:6, padding:'6px 10px' }}>
                          "{ev.source_excerpt.slice(0,120)}{ev.source_excerpt.length>120?'…':''}"
                        </div>
                      )}
                      {ev.is_paradox && ev.paradox_note && (
                        <div style={{ marginTop:8, background:c.dangerLight, borderRadius:7, padding:'8px 12px', fontSize:12, color:c.danger }}>
                          ⚠️ {ev.paradox_note}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )
          }
        </div>
      )}
    </div>
  )
}

// ─── Disposition tab ─────────────────────────────────────────────────────────────
function DispositionTab({ rec }) {
  if (!rec) return (
    <div style={{ ...s.infoBox, color: c.textMuted, fontSize: 14, lineHeight: 1.6 }}>
      Disposition recommendation generates after Stage 2 review is complete.
    </div>
  )
  const col  = dispositionColor[rec.disposition] || dispositionColor.REQUEST_MORE_INFO
  const icon = { APPROVE:'✅', DENY:'❌', REQUEST_MORE_INFO:'⚠️' }[rec.disposition] || '—'

  return (
    <div>
      <div style={{ background:c.bg, border:`1px solid ${c.border}`, borderRadius:10, padding:'12px 16px', marginBottom:22, fontSize:13, color:c.textMuted, display:'flex', gap:10, lineHeight:1.6 }}>
        <span>ℹ️</span>
        <span><strong style={{ color:c.text }}>Decision-support only.</strong> A licensed human adjuster must make the final determination. All citations must be verified against source documents.</span>
      </div>
      <div style={{ borderRadius:12, padding:'24px 26px', marginBottom:22, background:col.bg, border:`1.5px solid ${col.border}` }}>
        <div style={{ display:'flex', alignItems:'center', gap:18, marginBottom:14 }}>
          <span style={{ fontSize:40, lineHeight:1 }}>{icon}</span>
          <div>
            <div style={{ fontSize:24, fontWeight:800, color:col.color, fontFamily:font.heading, letterSpacing:'-0.3px' }}>{rec.disposition.replace(/_/g,' ')}</div>
            <div style={{ fontSize:13, color:col.color, opacity:.75, marginTop:3 }}>Confidence: <strong>{rec.confidence}</strong></div>
          </div>
        </div>
        <p style={{ fontSize:14, color:c.text, lineHeight:1.7, margin:0 }}>{rec.rationale}</p>
      </div>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(280px, 1fr))', gap:16 }}>
        {rec.supporting_findings?.length > 0 && (
          <div style={{ ...s.infoBox }}>
            <div style={{ fontSize:11, fontWeight:600, color:c.textMuted, textTransform:'uppercase', letterSpacing:'.7px', marginBottom:8 }}>Supporting Findings</div>
            <ul style={{ margin:0, paddingLeft:18 }}>
              {rec.supporting_findings.map((f,i) => <li key={i} style={{ fontSize:13, marginBottom:6, color:c.text, lineHeight:1.5 }}>{f}</li>)}
            </ul>
          </div>
        )}
        {rec.blocking_issues?.length > 0 && (
          <div style={{ background:c.dangerLight, borderRadius:10, padding:'14px 18px', border:`1px solid #fecaca` }}>
            <div style={{ fontSize:11, fontWeight:600, color:c.danger, textTransform:'uppercase', letterSpacing:'.7px', marginBottom:8 }}>Blocking Issues</div>
            <ul style={{ margin:0, paddingLeft:18 }}>
              {rec.blocking_issues.map((issue,i) => <li key={i} style={{ fontSize:13, marginBottom:6, color:c.danger, lineHeight:1.5 }}>{issue}</li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Upload pane ─────────────────────────────────────────────────────────────────
function UploadPane({ onRunCreated }) {
  const [files,    setFiles]    = useState([])
  const [rulebook, setRulebook] = useState('')
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const submit = async () => {
    if (!files.length) { setError('Select at least one document.'); return }
    setLoading(true); setError(null)
    try { onRunCreated((await api.createRun(files, rulebook)).run_id) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <div style={s.card}>
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ fontSize:20, fontWeight:700, color:c.text, fontFamily:font.heading, marginBottom:6 }}>New Analysis Run</h2>
        <p style={{ color:c.textMuted, fontSize:14, lineHeight:1.5 }}>
          Upload Indian insurance claim documents. The 9-node pipeline analyses, detects conflicts, checks rules, and pauses at human review gates before proceeding.
        </p>
      </div>

      <div style={{ marginBottom:20 }}>
        <label style={{ fontSize:11, fontWeight:600, marginBottom:6, display:'block', color:c.textMuted, textTransform:'uppercase', letterSpacing:'.7px' }}>
          Documents (PDF, DOCX, TXT)
        </label>
        <div style={{ border:`2px dashed ${c.border}`, borderRadius:10, padding:'28px 24px', textAlign:'center', background:c.bg, cursor:'pointer', position:'relative' }}>
          <div style={{ fontSize:32, marginBottom:10 }}>📄</div>
          <div style={{ fontSize:14, color:c.textMuted, marginBottom:6 }}>
            Drop files here or <span style={{ color:c.primary, fontWeight:500 }}>browse</span>
          </div>
          <div style={{ fontSize:12, color:c.textFaint }}>PDF, DOCX, TXT · max 5 files per run</div>
          <input type="file" multiple accept=".pdf,.docx,.doc,.txt,.md"
            style={{ position:'absolute', inset:0, opacity:0, cursor:'pointer' }}
            onChange={e => {
              const selected = Array.from(e.target.files)
              if (selected.length > 5) {
                alert('Maximum 5 files per run. Only the first 5 will be used.')
                setFiles(selected.slice(0, 5))
              } else {
                setFiles(selected)
              }
            }} />
        </div>
        {files.length > 0 && (
          <div style={{ marginTop:10, background:c.primaryLight, borderRadius:8, padding:'10px 14px', fontSize:13, color:c.primary }}>
            ✓ {files.length}/5 file{files.length>1?'s':''} selected: {files.map(f=>f.name).join(', ')}
          </div>
        )}
      </div>

      <div style={{ marginBottom:24 }}>
        <label style={{ fontSize:11, fontWeight:600, marginBottom:6, display:'block', color:c.textMuted, textTransform:'uppercase', letterSpacing:'.7px' }}>
          Rulebook / Checklist <span style={{ fontWeight:400, textTransform:'none', letterSpacing:0 }}>(optional)</span>
        </label>
        <textarea style={s.textarea} value={rulebook} onChange={e => setRulebook(e.target.value)}
          placeholder={'One rule per line:\n• Claim amount must not exceed policy limit\n• Incident date must fall within the policy period'} />
      </div>

      {error && (
        <div style={{ background:c.dangerLight, borderRadius:8, padding:'10px 14px', fontSize:13, color:c.danger, marginBottom:16 }}>{error}</div>
      )}
      <button style={{ ...s.btn, ...s.btnPrimary, fontSize:15, padding:'12px 32px' }} onClick={submit} disabled={loading}>
        {loading ? 'Starting analysis…' : 'Start Analysis →'}
      </button>
    </div>
  )
}

// ─── Main run view ───────────────────────────────────────────────────────────────
const TABS = [
  { id: 'overview',     label: 'Overview' },
  { id: 'review',      label: 'Review' },
  { id: 'analysis',    label: 'Analysis' },
  { id: 'disposition', label: 'Disposition' },
  { id: 'dev',         label: 'Dev' },
]

function RunView({ runId }) {
  const [status, setStatus] = useState(null)
  const [logs,   setLogs]   = useState([])
  const [items,  setItems]  = useState([])
  const [report, setReport] = useState(null)
  const [cost,   setCost]   = useState(null)
  const [tab,    setTab]    = useState('overview')
  const [devSub, setDevSub] = useState('logs')

  const refresh = useCallback(async () => {
    try {
      const [st, lg, rv] = await Promise.all([
        api.getRunStatus(runId),
        api.getRunLogs(runId),
        api.getReviewItems(runId),
      ])
      setStatus(st)
      setLogs(lg.logs || [])
      setItems(rv.items || [])
    } catch(e) { console.error(e) }
  }, [runId])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  const loadReport = useCallback(async () => {
    const r = await api.getReport(runId)
    setReport(r)
  }, [runId])

  useEffect(() => {
    if (['review','analysis','disposition'].includes(tab)) loadReport()
    if (tab === 'dev' && devSub === 'cost' && !cost) api.getCost(runId).then(setCost)
  }, [tab, devSub, loadReport])

  const onDecide = async (itemId, approved, note) => {
    if (approved) await api.approveItem(runId, itemId, note)
    else          await api.rejectItem(runId, itemId, note)
    await refresh()
  }

  const onResume = async () => {
    await api.resumeRun(runId, status?.current_stage || 1)
    await refresh()
  }

  const pending     = items.filter(i => i.status === 'pending')
  const signalCount = report?.fraud_signals?.length || 0
  const paradoxCount= report?.timeline_events?.filter(e=>e.is_paradox).length || 0
  const hasPaused   = status?.status === 'paused_hitl'

  const tabLabel = (t) => {
    if (t.id === 'review' && pending.length > 0)
      return <>{t.label} <span style={{ marginLeft:4, background:c.danger, color:'#fff', borderRadius:99, padding:'1px 6px', fontSize:10, fontWeight:700 }}>{pending.length}</span></>
    if (t.id === 'analysis' && (signalCount || paradoxCount))
      return <>{t.label} <span style={{ marginLeft:4, background:'#d97706', color:'#fff', borderRadius:99, padding:'1px 6px', fontSize:10, fontWeight:700 }}>{signalCount + paradoxCount}</span></>
    return t.label
  }

  return (
    <div style={s.card}>
      {/* Run header */}
      <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', gap:12, flexWrap:'wrap', marginBottom:28 }}>
        <div>
          <h2 style={{ fontSize:18, fontWeight:700, color:c.text, fontFamily:font.heading, marginBottom:5 }}>
            Run <code style={{ fontFamily:font.mono, fontSize:15, color:c.primary, fontWeight:700 }}>{runId.slice(0,8)}…</code>
          </h2>
          {status && (
            <div style={{ fontSize:13, color:c.textMuted }}>
              {status.document_count} doc{status.document_count!==1?'s':''} · {status.facts_extracted} facts · {status.conflicts_found} conflict{status.conflicts_found!==1?'s':''}
            </div>
          )}
        </div>
        {status && <Badge status={status.status} />}
      </div>

      {/* Pipeline stepper */}
      {status && <PipelineStepper status={status.status} stage={status.current_stage} node={status.current_node} />}

      {/* HITL pause alert */}
      {hasPaused && pending.length > 0 && (
        <div style={{ background:'#fef2f2', border:'1.5px solid #fecaca', borderRadius:12, padding:'14px 18px', marginBottom:20, display:'flex', gap:12, alignItems:'flex-start' }}>
          <span style={{ fontSize:18, flexShrink:0 }}>🔴</span>
          <div>
            <div style={{ fontWeight:700, fontSize:14, color:c.danger, marginBottom:4 }}>
              Paused at Review Gate — {pending.length} item{pending.length>1?'s':''} waiting
            </div>
            <div style={{ fontSize:13, color:'#991b1b' }}>
              Switch to the <strong>Review</strong> tab, read each item carefully, then approve or reject before the pipeline can continue.
            </div>
          </div>
          <button style={{ ...s.btn, background:c.danger, color:'#fff', fontSize:13, flexShrink:0, marginLeft:'auto' }} onClick={() => setTab('review')}>
            Go to Review →
          </button>
        </div>
      )}

      {/* Caution banner (only on review tab) */}
      {tab === 'review' && <CautionBanner items={items} report={report} />}

      {/* Tab navigation */}
      <div style={{ display:'flex', gap:0, borderBottom:`1px solid ${c.border}`, marginBottom:28, overflowX:'auto' }}>
        {TABS.map(t => {
          const active = tab === t.id
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              padding:'10px 18px', border:'none', background:'none', cursor:'pointer',
              fontSize:13, fontWeight:active?600:400,
              color:active?c.primary:c.textMuted,
              borderBottom:`2px solid ${active?c.primary:'transparent'}`,
              marginBottom:-1, whiteSpace:'nowrap', fontFamily:font.body,
            }}>
              {tabLabel(t)}
            </button>
          )
        })}
      </div>

      {/* ── Overview tab ── */}
      {tab === 'overview' && status && (
        <div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(140px, 1fr))', gap:14, marginBottom:22 }}>
            {[
              { label:'Documents',     value: status.document_count||0,             color: c.primary },
              { label:'Facts Extracted',value: status.facts_extracted||0,           color: c.primary },
              { label:'Conflicts',     value: status.conflicts_found||0,             color: status.conflicts_found>0?c.danger:c.success },
              { label:'Pending Review',value: status.review_items_pending||0,        color: status.review_items_pending>0?'#d97706':c.success },
              { label:'Fraud Signals', value: signalCount,                           color: signalCount>0?'#d97706':c.success },
              { label:'Paradoxes',     value: paradoxCount,                          color: paradoxCount>0?c.danger:c.success },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ ...s.infoBox, textAlign:'center' }}>
                <div style={{ fontSize:28, fontWeight:800, color, fontFamily:font.heading, lineHeight:1 }}>{value}</div>
                <div style={{ fontSize:11, color:c.textFaint, marginTop:5 }}>{label}</div>
              </div>
            ))}
          </div>

          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(160px, 1fr))', gap:12, marginBottom:20 }}>
            {[
              { label:'Stage',        value:`${status.current_stage} / 3` },
              { label:'Current Node', value:status.current_node||'—' },
              { label:'Started',      value:status.started_at?new Date(status.started_at).toLocaleTimeString():'—' },
            ].map(({ label, value }) => (
              <div key={label} style={s.infoBox}>
                <div style={{ fontSize:11, fontWeight:600, color:c.textMuted, textTransform:'uppercase', letterSpacing:'.7px', marginBottom:5 }}>{label}</div>
                <div style={{ fontWeight:600, fontSize:14, color:c.text, fontFamily:font.mono }}>{value}</div>
              </div>
            ))}
          </div>

          {status.error && (
            <div style={{ background:c.dangerLight, border:`1px solid #fecaca`, borderRadius:10, padding:'12px 16px', color:c.danger, fontSize:13 }}>
              ⚠️ {status.error}
            </div>
          )}
        </div>
      )}

      {/* ── Review tab ── */}
      {tab === 'review' && (
        <ReviewTab
          items={items}
          report={report}
          onDecide={onDecide}
          onResume={onResume}
          runStatus={status?.status}
          currentStage={status?.current_stage}
        />
      )}

      {/* ── Analysis tab ── */}
      {tab === 'analysis' && <AnalysisTab report={report} />}

      {/* ── Disposition tab ── */}
      {tab === 'disposition' && <DispositionTab rec={report?.disposition_recommendation} />}

      {/* ── Dev tab ── */}
      {tab === 'dev' && (
        <div>
          <div style={{ display:'flex', gap:8, marginBottom:20 }}>
            {['logs','cost','diff'].map(sub => (
              <button key={sub} onClick={() => { setDevSub(sub); if(sub==='cost'&&!cost) api.getCost(runId).then(setCost) }}
                style={{ ...s.btn, background:devSub===sub?c.primary:c.tagBg, color:devSub===sub?'#fff':c.textMuted, border:'none', padding:'7px 16px', fontSize:13, textTransform:'capitalize' }}>
                {sub}
              </button>
            ))}
          </div>

          {devSub === 'logs' && (
            <div style={s.log}>
              {!logs.length && <div style={{ color:'#737373' }}>No logs yet.</div>}
              {logs.map((l,i) => (
                <div key={i} style={{ marginBottom:4 }}>
                  <span style={{ color:'#60a5fa' }}>[Stage {l.stage}]</span>{' '}
                  <span style={{ color:'#4ade80' }}>{l.node}</span>{' '}
                  <span style={{ color:l.decision==='continue'?'#facc15':l.decision==='escalate'?'#f87171':'#fde68a' }}>→ {l.decision}</span>
                  {l.output && <span style={{ color:'#737373' }}> | {l.output}</span>}
                  {l.error  && <span style={{ color:'#f87171' }}> ⚠ {l.error}</span>}
                  {l.duration_ms && <span style={{ color:'#525252' }}> ({l.duration_ms}ms)</span>}
                </div>
              ))}
            </div>
          )}

          {devSub === 'cost' && cost && (
            <div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:14, marginBottom:22 }}>
                {[
                  { label:'Total Cost',  value:`$${cost.total_cost_usd?.toFixed(4)}`,           sub:'USD (Groq paid-tier rates)', highlight:true },
                  { label:'Tokens In',   value:cost.total_tokens_in?.toLocaleString(),           sub:'prompt tokens' },
                  { label:'Tokens Out',  value:cost.total_tokens_out?.toLocaleString(),          sub:'completion tokens' },
                ].map(({ label, value, sub, highlight }) => (
                  <div key={label} style={{ ...s.infoBox, textAlign:'center' }}>
                    <div style={{ fontSize:11, fontWeight:600, color:c.textMuted, textTransform:'uppercase', letterSpacing:'.7px', marginBottom:5 }}>{label}</div>
                    <div style={{ fontSize:22, fontWeight:800, fontFamily:font.heading, color:highlight?c.primary:c.text, lineHeight:1, marginBottom:3 }}>{value}</div>
                    <div style={{ fontSize:11, color:c.textFaint }}>{sub}</div>
                  </div>
                ))}
              </div>
              <table style={s.table}>
                <thead><tr>{['Node','Stage','In','Out','Cost (USD)'].map(h=><th key={h} style={s.th}>{h}</th>)}</tr></thead>
                <tbody>
                  {cost.by_stage?.map((row,i) => (
                    <tr key={i} style={{ background:i%2===0?'transparent':c.bg }}>
                      <td style={{ ...s.td, fontFamily:font.mono, color:c.primary }}>{row.node}</td>
                      <td style={s.td}>{row.stage}</td>
                      <td style={s.td}>{row.tokens_in?.toLocaleString()}</td>
                      <td style={s.td}>{row.tokens_out?.toLocaleString()}</td>
                      <td style={{ ...s.td, fontFamily:font.mono }}>${row.cost_usd?.toFixed(5)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {devSub === 'diff' && (
            !report?.report_diff?.length
              ? <div style={{ ...s.infoBox, color:c.textMuted, fontSize:14 }}>No Stage 3 diffs yet.</div>
              : report.report_diff.map((ch,i) => {
                  const col={update:c.primary,addition:c.success,conflict_flag:c.danger}[ch.change_type]||c.textMuted
                  return (
                    <div key={i} style={{ border:`1px solid ${c.border}`, borderLeft:`4px solid ${col}`, borderRadius:10, padding:'14px 18px', marginBottom:12, background:c.surface }}>
                      <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:8, flexWrap:'wrap' }}>
                        <span style={{ ...s.pill, background:col+'18', color:col }}>{ch.change_type}</span>
                        <span style={{ fontWeight:600, fontSize:14, color:c.text }}>{ch.section}</span>
                        <span style={{ fontSize:12, color:c.textFaint, marginLeft:'auto' }}>from {ch.source_doc}</span>
                      </div>
                      {ch.old_content && <div style={{ background:'#fef2f2', borderRadius:7, padding:'9px 13px', fontSize:12, fontFamily:font.mono, marginBottom:6, color:c.danger }}>− {ch.old_content.slice(0,200)}</div>}
                      <div style={{ background:'#f0fdf4', borderRadius:7, padding:'9px 13px', fontSize:12, fontFamily:font.mono, marginBottom:8, color:c.success }}>+ {ch.new_content.slice(0,200)}</div>
                      <div style={{ fontSize:12, color:c.textMuted }}>Reason: {ch.reason}</div>
                    </div>
                  )
                })
          )}
        </div>
      )}
    </div>
  )
}

// ─── Root ────────────────────────────────────────────────────────────────────────
export default function App() {
  const [runId,   setRunId]   = useState(null)
  const [history, setHistory] = useState([])

  const onRunCreated = (id) => { setRunId(id); setHistory(h => [id, ...h]) }

  return (
    <div style={s.app}>
      {/* Header */}
      <div style={{ marginBottom:40, paddingBottom:28, borderBottom:`1px solid ${c.border}` }}>
        <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', flexWrap:'wrap', gap:14 }}>
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:8 }}>
              <h1 style={{ fontSize:30, fontWeight:800, color:c.text, fontFamily:font.heading, letterSpacing:'-0.6px' }}>DocTask</h1>
              <span style={{ background:c.primaryLight, color:c.primary, borderRadius:6, padding:'3px 10px', fontSize:12, fontWeight:600 }}>
                v1.0 · Tej Thakar
              </span>
            </div>
            <p style={{ color:c.textMuted, fontSize:14, marginTop:6, lineHeight:1.6 }}>
              Agentic insurance claims analysis · India-specific · 9-node LangGraph pipeline · Human-gated · Resumable
            </p>
          </div>
          <div style={{ display:'flex', gap:8, flexWrap:'wrap', alignItems:'center' }}>
            <span style={{ background:c.tagBg, border:`1px solid ${c.border}`, borderRadius:8, padding:'6px 13px', fontSize:12, color:c.textMuted }}>⚡ Groq</span>
            <span style={{ background:c.tagBg, border:`1px solid ${c.border}`, borderRadius:8, padding:'6px 13px', fontSize:12, color:c.textMuted }}>🔗 SuperDocs API</span>
          </div>
        </div>
      </div>

      {/* Content */}
      {!runId ? (
        <UploadPane onRunCreated={onRunCreated} />
      ) : (
        <div>
          <div style={{ display:'flex', gap:12, alignItems:'center', marginBottom:20 }}>
            <button style={{ ...s.btn, ...s.btnGhost }} onClick={() => setRunId(null)}>← New Run</button>
            {history.length > 1 && (
              <select style={{ ...s.input, width:'auto', cursor:'pointer' }} value={runId} onChange={e => setRunId(e.target.value)}>
                {history.map(id => <option key={id} value={id}>{id.slice(0,8)}…</option>)}
              </select>
            )}
          </div>
          <RunView runId={runId} />
        </div>
      )}
    </div>
  )
}
