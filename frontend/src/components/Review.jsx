import React, { useMemo, useState } from 'react'
import { api } from '../api.js'
import { Chip, Rationale, RoleBadge } from './common.jsx'
import { RawLink } from './Raw.jsx'

const GRADE = { 0: 'Grading not reported', 1: 'Group 1 · Assoc. w/ R', 2: 'Group 2 · Assoc. w/ R (interim)', 3: 'Group 3 · Uncertain', 5: 'Group 5 · Not assoc. w/ R' }

/* The queue fills with gradings the Evidence Analyst flagged as uncertain or ambiguous. Only the
 * TB Microbiologist can decide them, one at a time or in bulk when there is more than a handful
 * (threshold: >5 pending). The bulk panel mirrors the Stage 2 hold-resolver so the UX is familiar:
 * checkboxes on each pending card, select-all / clear, a shared rationale, and one button per
 * decision. Non-pending items (already reviewed) never appear in the bulk selection. */
const BULK_THRESHOLD = 5

export default function Review({ st, act, who, openSample }) {
  const fs = st.samples.flatMap(s => s.findings).filter(f => f.review !== 'Not required')
  const pending = useMemo(() => fs.filter(f => f.review === 'Pending'), [fs])
  const [bulk, setBulk] = useState(() => new Set())
  const [bulkWhy, setBulkWhy] = useState('')
  const SHOW_BULK = pending.length > BULK_THRESHOLD
  const bulkFids = pending.map(f => f.fid).filter(fid => bulk.has(fid))
  const bulkToggle = (fid) => setBulk(prev => { const s = new Set(prev); s.has(fid) ? s.delete(fid) : s.add(fid); return s })
  const bulkDecide = (decision) => act(async () => {
    if (!bulkWhy.trim()) throw new Error('A rationale is required.')
    const results = await Promise.allSettled(bulkFids.map(fid => api.review({ ...who, fid, decision, rationale: bulkWhy })))
    const failed = results.filter(r => r.status === 'rejected').length
    if (failed) throw new Error(`${results.length - failed} applied, ${failed} failed`)
    setBulk(new Set()); setBulkWhy('')
  }, `${bulkFids.length} finding(s) marked as ${decision}`)

  if (!fs.length) return <div className="panel"><p className="muted">The queue fills after Stage 5: uncertain gradings, low depth, minor variants and discordance wait here for the TB Microbiologist.</p></div>
  return (
    <>
      <p className="role-reqd">Only <RoleBadge role="tbexpert" /> can change scientific review status. The Evidence Analyst's note is an AI draft to help the reviewer, never a decision.</p>
      {SHOW_BULK && <div className="box gate" style={{ gap: 6 }}>
        <div className="row between"><h3>Bulk resolve · {pending.length} pending finding(s)</h3>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn small" onClick={() => setBulk(new Set(pending.map(f => f.fid)))}>Select all</button>
            <button className="btn small ghost" onClick={() => setBulk(new Set())}>Clear</button>
          </div></div>
        <textarea value={bulkWhy} onChange={e => setBulkWhy(e.target.value)} placeholder="Shared rationale (applied to every selected finding)" aria-label="Bulk rationale" />
        <div className="row"><span className="muted" style={{ fontSize: '.82rem' }}>{bulkFids.length} selected</span>
          <button className="btn small primary" disabled={!bulkFids.length} onClick={() => bulkDecide('Reviewed')}>Supports resistance</button>
          <button className="btn small" disabled={!bulkFids.length} onClick={() => bulkDecide('Not supported')}>Not supported</button>
          <button className="btn small" disabled={!bulkFids.length} onClick={() => bulkDecide('Needs more data')}>Needs more data</button>
        </div></div>}
      <div className="team">{fs.map(f => (
        <div className="panel" key={f.fid} style={{ gap: 10 }}>
          <div className="row between">
            <div className="row" style={{ gap: 8 }}>
              {SHOW_BULK && f.review === 'Pending' && <input type="checkbox" checked={bulk.has(f.fid)} onChange={() => bulkToggle(f.fid)} aria-label={`Select ${f.sample_id} ${f.gene} ${f.change} for bulk`} />}
              <button className="btn small ghost mono" onClick={() => openSample(f.sample_id)}>{f.sample_id}</button>
            </div>
            <Chip label={f.review} kind={f.review.split(' ')[0]} /></div>
          <h3><span className="mono">{f.gene} {f.change}</span> · {f.drug}</h3>
          <dl className="kv"><dt>Grading</dt><dd>{GRADE[f.grade] || f.confidence}</dd><dt>Depth</dt><dd>{f.depth ?? 'n/a'} reads{f.freq < 1 ? ` · ${Math.round(f.freq * 100)}% of reads` : ''}</dd><dt>Why here</dt><dd>{f.reason}</dd></dl>
          {f.interpretation && <div className="box note"><span className="eyebrow">Evidence Analyst note · AI draft</span><p style={{ fontSize: '.88rem' }}>{f.interpretation}</p></div>}
          {f.review === 'Pending'
            ? <Rationale id={'r-' + f.fid} placeholder="e.g. Borderline rpoB mutation; DST can miss it." buttons={[['Reviewed', 'Supports resistance', true], ['Not supported', 'Not supported'], ['Needs more data', 'Needs more data']]}
              extra={<RawLink kind="tbprofiler" k={f.sample_id} />}
              onSubmit={(d, r) => act(() => api.review({ ...who, fid: f.fid, decision: d, rationale: r }), 'Review recorded')} />
            : <p style={{ fontSize: '.86rem' }}><b>{f.reviewer}:</b> {f.rationale}</p>}
        </div>))}</div>
    </>
  )
}
