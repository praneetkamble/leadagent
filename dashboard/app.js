(function () {
  'use strict';
  var $ = function (s) { return document.querySelector(s); };
  var esc = function (s) { var d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; };
  var current = null;

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.detail || ('HTTP ' + r.status));
        return j;
      });
    });
  }
  function post(path, body) { return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); }

  function loadInfo() {
    api('/api/info').then(function (i) {
      $('#info').textContent = 'LLM: ' + i.llm + ' · live URL fetch: ' + (i.url_fetch ? 'on' : 'off') + ' · min fit to draft: ' + i.min_fit;
      var sel = $('#fixture'); sel.innerHTML = '';
      i.fixtures.forEach(function (f) { var o = document.createElement('option'); o.value = f; o.textContent = f.replace(/_/g, ' '); sel.appendChild(o); });
    });
  }
  function loadRuns() {
    api('/api/runs').then(function (rs) {
      var ul = $('#runs'); ul.innerHTML = '';
      if (!rs.length) { ul.innerHTML = '<li class="hint">No runs yet.</li>'; return; }
      rs.forEach(function (r) {
        var li = document.createElement('li'); if (current && current.id === r.id) li.className = 'on';
        li.innerHTML = '<button type="button"><b>' + esc(r.business) + '</b> <span class="pill ' + esc(r.status) + '">' + esc(r.status.replace(/_/g, ' ')) + '</span><br><small>score ' + esc(r.score) + ' · ' + esc(r.source) + '</small></button>';
        li.firstChild.onclick = function () { open(r.id); };
        ul.appendChild(li);
      });
    });
  }
  function open(id) { api('/api/runs/' + id).then(render); }

  function render(run) {
    current = run; loadRuns();
    var h = '<div class="head"><div><h2>' + esc(run.business || 'Run failed') + '</h2><span class="pill ' + esc(run.status) + '">' + esc(run.status.replace(/_/g, ' ')) + '</span> <small class="ev">' + esc(run.source) + '</small></div>';
    if (run.fit) h += '<div class="score">' + run.fit.score + '<small> / 100 · ' + esc(run.fit.tier) + '</small></div>';
    h += '</div>';
    if (run.error) h += '<p class="msg">' + esc(run.error) + '</p>';
    if (run.fit) {
      h += '<div class="two"><div><h3>Scoring rubric (transparent)</h3><table class="rub">';
      run.fit.items.forEach(function (it) {
        h += '<tr class="' + (it.hit ? '' : 'no') + '"><td>' + esc(it.description) + (it.evidence ? '<div class="ev">evidence: ' + esc(it.evidence) + '</div>' : '') + '</td><td style="width:80px"><div class="bar"><i style="width:' + (it.earned / it.max * 100) + '%"></i></div></td><td style="width:50px;text-align:right"><b>' + it.earned + '</b>/' + it.max + '</td></tr>';
      });
      h += '</table>' + (run.fit.capped_for_chain ? '<p class="ev">Score capped at 20: chain/franchise.</p>' : '') + '</div><div><h3>Step-by-step trace</h3><ul class="trace">';
      run.trace.forEach(function (t) {
        h += '<li class="' + esc(t.mode) + '"><code>' + esc(t.mode) + '</code><b>' + esc(t.step) + '</b> <small>' + esc(t.ms) + ' ms</small><br>' + esc(t.summary) + '</li>';
      });
      h += '</ul></div></div>';
    }
    if (run.draft) {
      var awaiting = run.status === 'awaiting_approval';
      h += '<h3>Draft pitch ' + (awaiting ? '(needs your decision)' : '') + '</h3><div class="draft">';
      h += '<label class="lbl" for="dSub">Subject</label><input type="text" id="dSub" value="' + esc(run.draft.subject) + '"' + (awaiting ? '' : ' disabled') + '>';
      h += '<label class="lbl" for="dBody" style="margin-top:8px">Body</label><textarea id="dBody"' + (awaiting ? '' : ' disabled') + '>' + esc(run.draft.body) + '</textarea>';
      if (run.grounding) h += '<p class="ground ' + (run.grounding.passed ? 'good' : 'bad') + '">Grounding check: ' + (run.grounding.passed ? 'passed (numbers and links come from the site or profile)' : 'FAILED: ' + esc(run.grounding.problems.join('; '))) + '</p>';
      if (awaiting) h += '<div class="gate"><button class="ok" id="bApprove" type="button"' + (run.grounding && !run.grounding.passed ? ' disabled' : '') + '>Approve</button><button class="alt" id="bEdit" type="button">Save edit</button><button class="alt" id="bReject" type="button">Reject</button></div><p id="gMsg" class="msg"></p>';
      else if (run.status === 'approved') h += '<p class="ground good">Approved. Saved to the outbox folder as a text file. LeadAgent does not send email: you send it yourself.</p>';
      h += '</div>';
    } else if (run.status === 'skipped_low_fit') {
      h += '<p class="hint">Not a good fit, so no pitch was drafted. Tick “Draft even if fit is weak” and run again to override.</p>';
    }
    if (run.facts) {
      var digest = {}; Object.keys(run.facts).forEach(function (k) { digest[k] = run.facts[k].value; });
      h += '<details><summary>Extracted facts (JSON)</summary><pre>' + esc(JSON.stringify(digest, null, 1)) + '</pre></details>';
    }
    $('#detail').innerHTML = h;
    var a = $('#bApprove');
    if (a) {
      var send = function (action) {
        post('/api/runs/' + run.id + '/decision', { action: action, subject: $('#dSub').value, body: $('#dBody').value, reason: action === 'reject' ? (prompt('Reason (optional)') || '') : '' })
          .then(render).catch(function (e) { $('#gMsg').textContent = e.message; });
      };
      a.onclick = function () { send('approve'); };
      $('#bEdit').onclick = function () { send('edit'); };
      $('#bReject').onclick = function () { send('reject'); };
    }
  }

  $('#go').addEventListener('click', function () {
    $('#runMsg').textContent = '';
    post('/api/runs', { source: $('#fixture').value, force_draft: $('#force').checked }).then(render).catch(function (e) { $('#runMsg').textContent = e.message; });
  });
  loadInfo(); loadRuns();
})();
