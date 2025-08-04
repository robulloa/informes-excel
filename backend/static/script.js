document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("uploadForm");
    const tableBody = document.querySelector("#dataTable tbody");

    loadData();

    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fileInput = document.getElementById("file");

            const formData = new FormData();
            formData.append("file", fileInput.files[0]);

            const response = await fetch("/upload", {
                method: "POST",
                body: formData,
            });

            const result = await response.json();
            if (result.error) {
                alert(result.error);
            } else {
                alert(result.message);
                loadData();
            }
        });
    }

    async function loadData() {
        const response = await fetch("/data");
        const data = await response.json();
        tableBody.innerHTML = "";
        data.forEach(row => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td>${row.id}</td>
                <td>${row.nombre}</td>
                <td>${row.email}</td>
                <td>${row.puntaje}</td>
            `;
            tableBody.appendChild(tr);
        });
    }
});

