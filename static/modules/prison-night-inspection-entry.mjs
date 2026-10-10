// Standalone read-only integration of the provided HTML demo. All demo JS/CSS and
// fixture state live in a sandboxed iframe, never in the training platform realm.
const DEMO_URL='/static/isolated/prison-night-inspection-demo.html?v=20261010a';
export function renderPrisonNightInspectionPage(){
  const view=document.getElementById('view');
  if(!view)return false;
  if(view.querySelector('#nightInspectionIsolated iframe'))return true;
  view.innerHTML=`<section id="nightInspectionIsolated" aria-label="监所夜间离床风险智能研判系统">
    <iframe title="监所夜间离床风险智能研判系统（独立演示）" src="${DEMO_URL}"
      sandbox="allow-scripts allow-modals" referrerpolicy="no-referrer" loading="eager"></iframe>
  </section>`;
  return true;
}
