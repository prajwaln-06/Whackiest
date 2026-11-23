const form = document.querySelector("#application");
const screens = [...form.querySelectorAll("[data-screen]")];
const error = document.querySelector("#portal-error");
const joint = document.querySelector("#joint");
const delivery = document.querySelector("#delivery");
const options = document.querySelector("#delivery-list");
const verification = document.querySelector("#verification");
const shapes = { circle: "●", square: "■", triangle: "▲" };
let step = 1;
let verified = false;
let expectedShape = "";

function showError(message = "") {
  error.textContent = message;
  error.hidden = !message;
}

function showStep(next) {
  step = next;
  screens.forEach((section, index) => { section.hidden = index !== next - 1; });
  document.querySelector("#progress").textContent = "Step " + next + " of 4";
  showError();
  window.scrollTo(0, 0);
}

function validCurrent() {
  for (const field of screens[step - 1].querySelectorAll("input, select")) {
    if (!field.closest("[hidden]") && !field.checkValidity()) {
      const label = field.labels?.[0]?.textContent.trim() || field.name;
      showError(label + ": " + field.validationMessage);
      field.reportValidity();
      return false;
    }
  }
  if (step === 3) {
    const file = document.querySelector("#proposal").files[0];
    if (!/\.(pdf|txt)$/i.test(file.name) || file.size > 10 * 1024 * 1024) {
      showError("Project Proposal: attach a PDF or TXT file up to 10 MB.");
      return false;
    }
    if (!document.querySelector("#delivery-value").value) {
      showError("Notice Transmittal Medium: select a delivery option.");
      return false;
    }
  }
  return true;
}

function renderReview() {
  const list = document.querySelector("#review");
  list.replaceChildren();
  for (const field of form.querySelectorAll("input, select")) {
    if (field.closest("#startup-block[hidden], #joint-block[hidden], #institution-block[hidden]")) continue;
    if (field.name === "legal_certification" || (["checkbox", "radio"].includes(field.type) && !field.checked)) continue;
    const label = field.type === "hidden" ? "Notice Transmittal Medium" : field.labels?.[0]?.textContent.trim() || field.name;
    const value = field.type === "file" ? field.files[0]?.name : field.type === "checkbox" ? "Confirmed"
      : field.type === "radio" ? field.labels[0].textContent.trim()
      : field.type === "select-one" ? field.selectedOptions[0]?.textContent : field.type === "hidden" ? delivery.textContent : field.value;
    const term = document.createElement("dt");
    const definition = document.createElement("dd");
    term.textContent = label;
    definition.textContent = value || "—";
    list.append(term, definition);
  }
}

form.addEventListener("change", (event) => {
  showError();
  if (event.target.name === "applicant_type") {
    document.querySelector("#startup-block").hidden = event.target.value !== "startup";
    document.querySelector("#institution-block").hidden = event.target.value !== "institution";
  }
  if (event.target === joint) document.querySelector("#joint-block").hidden = !joint.checked;
});

form.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.hasAttribute("data-prev")) showStep(step - 1);
  if (button.hasAttribute("data-next") && validCurrent()) {
    if (step === 3 && !verified) {
      expectedShape = Object.keys(shapes)[crypto.getRandomValues(new Uint32Array(1))[0] % 3];
      document.querySelector("#pattern").textContent = shapes[expectedShape];
      verification.hidden = false;
      verification.scrollIntoView({ block: "nearest" });
      return;
    }
    if (step === 3) renderReview();
    showStep(step + 1);
  }
  if (button === delivery) {
    options.hidden = !options.hidden;
    delivery.setAttribute("aria-expanded", String(!options.hidden));
  }
  if (button.dataset.value) {
    document.querySelector("#delivery-value").value = button.dataset.value;
    delivery.textContent = button.textContent;
    for (const option of options.children) option.setAttribute("aria-selected", String(option === button));
    options.hidden = true;
    delivery.setAttribute("aria-expanded", "false");
    showError();
  }
  if (button.dataset.shape) {
    if (button.dataset.shape !== expectedShape) {
      showError("The shape does not match. Try again.");
      return;
    }
    verified = true;
    verification.hidden = true;
    showError();
  }
});

form.noValidate = true;
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (step !== 4 || !verified || !validCurrent()) return;
  const submit = form.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    const response = await fetch("/applications", { method: "POST", body: new FormData(form) });
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.detail || "The registry could not issue a receipt.");
    }
    const receipt = await response.json();
    form.hidden = true;
    document.querySelector("#progress").hidden = true;
    document.querySelector("#reference").textContent = receipt.reference;
    document.querySelector("#received").textContent = "Received " + receipt.received;
    document.querySelector("#receipt").hidden = false;
    window.scrollTo(0, 0);
  } catch (error) {
    showError(error.message);
    submit.disabled = false;
  }
});
