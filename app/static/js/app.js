document.addEventListener("DOMContentLoaded", function () {
  const search = document.getElementById("tableSearch");
  const table = document.getElementById("recordsTable");
  if (search && table) {
    search.addEventListener("input", function () {
      const term = search.value.trim().toLocaleLowerCase();
      table.querySelectorAll("tbody tr").forEach(function (row) {
        row.hidden = !row.textContent.toLocaleLowerCase().includes(term);
      });
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const canvas = document.getElementById("appointmentChart");
  if (canvas && window.hospitalChartData && window.Chart) {
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: window.hospitalChartData.labels,
        datasets: [{
          label: "Appointments",
          data: window.hospitalChartData.values,
          backgroundColor: "#7da5ee",
          hoverBackgroundColor: "#2768d7",
          borderRadius: 5,
          maxBarThickness: 28
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { color: "#8793a6", font: { family: "DM Sans" } } },
          y: { beginAtZero: true, ticks: { precision: 0, color: "#8793a6" }, grid: { color: "#edf0f5" } }
        }
      }
    });
  }
});
