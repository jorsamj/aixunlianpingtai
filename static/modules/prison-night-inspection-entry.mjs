// Standalone read-only integration of the provided HTML demo. All demo JS/CSS and
// fixture state live in a sandboxed iframe, never in the training platform realm.
const DEMO_URL='/static/isolated/prison-night-inspection-demo.html?v=20261010b';
export function renderPrisonNightInspectionPage(){
  const view=document.getElementById('view');
  if(!view)return false;
  if(view.querySelector('#nightInspectionIsolated iframe'))return true;
  // Collapse only on entry; the user can expand the platform menu explicitly.
  document.body.classList.add('sidebar-collapsed');
  view.innerHTML=`<section id="nightInspectionIsolated" aria-label="AI算法底座">
    <iframe title="AI算法底座（独立演示）" src="${DEMO_URL}"
      sandbox="allow-scripts allow-modals" referrerpolicy="no-referrer" loading="eager"></iframe>
  </section>`;
  return true;
}
