import './style.css';

const root = document.querySelector<HTMLDivElement>('#app');
if (!root) throw new Error('Missing #app root');
root.textContent = 'Implement TASK.md here.';
