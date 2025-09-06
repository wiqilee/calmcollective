/**
 * Minimal front-end helpers
 * - Adds a breathing animation when the page loads (gentle cue)
 */
(function(){
  const footer = document.querySelector('.footer');
  if(!footer) return;

  // Simple 16s breathing tips loop
  let i = 0;
  const steps = [
    "Breathe in… 4 seconds",
    "Hold… 4 seconds",
    "Slow exhale… 6 seconds",
    "Rest… 2 seconds"
  ];
  const node = document.createElement('div');
  node.style.marginTop = '8px';
  node.style.opacity = '0.8';
  footer.appendChild(node);

  setInterval(()=>{
    node.textContent = steps[i % steps.length];
    i++;
  }, 4000);
})();

// Toggle Mood Info explanation
function toggleMoodInfo() {
  const el = document.getElementById('mood-info');
  if (el) el.classList.toggle('hidden');
}

// Register Service Worker
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js')
    .then(() => console.log("Service Worker registered successfully"))
    .catch(err => console.error("Service Worker registration failed:", err));
}
