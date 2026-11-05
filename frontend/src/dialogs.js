import Swal from "sweetalert2";
import "sweetalert2/dist/sweetalert2.min.css";

const appearance = {
  confirmButtonColor: "#126b5b",
  cancelButtonColor: "#edf4f1",
  buttonsStyling: false,
  customClass: {
    popup: "foodoo-dialog",
    title: "foodoo-dialog-title",
    htmlContainer: "foodoo-dialog-body",
    actions: "foodoo-dialog-actions",
    confirmButton: "foodoo-dialog-confirm",
    cancelButton: "foodoo-dialog-cancel",
    input: "foodoo-dialog-input",
  },
};

export async function confirmAction({
  title = "Are you sure?",
  text = "",
  confirmText = "Continue",
  danger = false,
} = {}) {
  const result = await Swal.fire({
    ...appearance,
    icon: danger ? "warning" : "question",
    title,
    text,
    showCancelButton: true,
    confirmButtonText: confirmText,
    cancelButtonText: "Cancel",
    reverseButtons: true,
    focusCancel: danger,
    customClass: {
      ...appearance.customClass,
      confirmButton: danger ? "foodoo-dialog-confirm foodoo-dialog-danger" : "foodoo-dialog-confirm",
    },
  });
  return result.isConfirmed;
}

export async function requestPassword(username) {
  // Password is never displayed in an audit log or application notification.
  const result = await Swal.fire({
    ...appearance,
    title: "Reset staff password",
    text: "Enter a new password for " + username + " (at least 10 characters).",
    input: "password",
    inputAttributes: {
      autocomplete: "new-password",
      minlength: "10",
      "aria-label": "New staff password",
    },
    inputPlaceholder: "New password",
    showCancelButton: true,
    confirmButtonText: "Reset password",
    cancelButtonText: "Cancel",
    reverseButtons: true,
    inputValidator: (value) => {
      if (!value || value.length < 10) return "Password must contain at least 10 characters.";
      return undefined;
    },
  });
  return result.isConfirmed ? result.value : null;
}

export function showAuditDetails(value) {
  return Swal.fire({
    ...appearance,
    icon: "info",
    title: "Order audit",
    text: String(value),
    confirmButtonText: "Close",
    customClass: {
      ...appearance.customClass,
      htmlContainer: "foodoo-dialog-body foodoo-audit-details",
    },
  });
}

const toast = Swal.mixin({
  toast: true,
  position: "top-end",
  showConfirmButton: false,
  timer: 3500,
  timerProgressBar: true,
  customClass: { popup: "foodoo-toast" },
});

export function showToast(message, icon = "success") {
  return toast.fire({
    icon,
    title: String(message),
    didOpen: (element) => {
      element.addEventListener("mouseenter", Swal.stopTimer);
      element.addEventListener("mouseleave", Swal.resumeTimer);
    },
  });
}
