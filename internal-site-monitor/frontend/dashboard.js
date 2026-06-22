const sites = JSON.parse(document.querySelector('#dashboard-data').textContent);
const siteContainer = document.querySelector('#sites');
const siteTemplate = document.querySelector('#site-template');
const statusIcons = { UP: '🟢', SLOW: '🐇', DOWN: '🔴' };

for (const site of sites) {
  const card = siteTemplate.content.cloneNode(true);
  const section = card.querySelector('.site');
  const link = card.querySelector('.site-url');

  section.classList.add(site.result.status.toLowerCase());
  card.querySelector('.site-name').textContent = site.name;
  card.querySelector('.status').textContent =
    `${statusIcons[site.result.status]} ${site.result.status}`;
  link.href = site.url;
  link.textContent = site.url;
  card.querySelector('.site-details').textContent =
    `HTTP ${site.result.status_code || '—'} · ${site.result.response_ms} ms · ${site.result.checked_at}`;
  siteContainer.appendChild(card);
}

const charts = sites.map((site, index) => {
  const canvas = document.querySelectorAll('.chart canvas')[index];

  return new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [{
        label: 'Response time (ms)',
        data: [],
        borderColor: '#334155',
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        tension: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: 'linear',
          grid: { color: '#e2e8f0' },
          ticks: {
            maxTicksLimit: 8,
            callback: value => new Date(value).toLocaleString(),
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: '#e2e8f0' },
          title: { display: true, text: 'ms' },
        },
      },
    },
  });
});

const range = document.querySelector('#range');
const savedRange = localStorage.getItem('monitor-range');

if ([...range.options].some(option => option.value === savedRange)) {
  range.value = savedRange;
}

function updateCharts() {
  localStorage.setItem('monitor-range', range.value);
  const now = Date.now();
  const duration = Number(range.value);

  sites.forEach((site, index) => {
    const timestamps = site.history.map(sample => new Date(sample.checked_at).getTime());
    const start = duration ? now - duration : Math.min(...timestamps, now);
    const visibleSamples = site.history.filter((sample, sampleIndex) =>
      timestamps[sampleIndex] >= start
    );

    charts[index].data.datasets[0].data = visibleSamples.map(sample => ({
      x: new Date(sample.checked_at).getTime(),
      y: sample.response_ms,
    }));
    charts[index].options.scales.x.min = start;
    charts[index].options.scales.x.max = now;
    charts[index].update();
  });
}

range.addEventListener('change', updateCharts);
updateCharts();

const autoRefresh = document.querySelector('#auto-refresh');
autoRefresh.checked = localStorage.getItem('monitor-auto-refresh') !== 'off';
let refreshTimer;

function scheduleRefresh() {
  clearInterval(refreshTimer);
  localStorage.setItem('monitor-auto-refresh', autoRefresh.checked ? 'on' : 'off');

  if (autoRefresh.checked) {
    refreshTimer = setInterval(() => location.reload(), 60_000);
  }
}

autoRefresh.addEventListener('change', scheduleRefresh);
scheduleRefresh();

document.querySelector('#search').addEventListener('input', event => {
  const query = event.target.value.toLowerCase();

  document.querySelectorAll('.site').forEach(site => {
    site.hidden = !site.textContent.toLowerCase().includes(query);
  });
});
