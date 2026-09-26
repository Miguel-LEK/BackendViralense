// New Check-In flow: creates an anonymous, ephemeral session for one submission.
// No login, no persistent identity by default.

function startNewCheckIn() {
  // Generate a fresh throwaway ID. This is NOT a user account -- it just lets
  // the backend group the vitals + symptoms + location from THIS one check-in.
  const checkInId = crypto.randomUUID();

  // Optional: if you want repeat check-ins from the same device to compare
  // against their own baseline, keep the ID around. Otherwise skip this line
  // entirely for full anonymity (each check-in becomes fully independent).
  localStorage.setItem("device_checkin_id", checkInId);

  return checkInId;
}

async function submitCheckIn({ checkInId, symptomScore, videoBlob }) {
  // 1. Get approximate location (never send exact coords to the backend --
  //    round here, before it ever leaves the browser)
  const position = await new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(resolve, reject)
  );
  const roundedLat = Math.round(position.coords.latitude * 100) / 100;   // ~1km precision
  const roundedLng = Math.round(position.coords.longitude * 100) / 100;

  // 2. Bundle everything for this one check-in
  const formData = new FormData();
  formData.append("checkin_id", checkInId);
  formData.append("timestamp", new Date().toISOString());
  formData.append("lat", roundedLat);
  formData.append("lng", roundedLng);
  formData.append("symptom_score", symptomScore);      // 0-1, from your symptom checkboxes
  formData.append("consent", "true");                  // only submit if user checked the consent box
  if (videoBlob) formData.append("video", videoBlob);  // short webcam clip for Presage

  // 3. Submit — backend forwards the video to Presage, computes the score,
  //    and stores the result tagged to this check-in only
  const response = await fetch("/api/checkin", {
    method: "POST",
    body: formData,
  });
  return response.json();
}

// Example wiring to a button in your UI:
// document.getElementById("new-checkin-btn").addEventListener("click", async () => {
//   const checkInId = startNewCheckIn();
//   // ... show webcam capture + symptom form, get videoBlob + symptomScore from user ...
//   const result = await submitCheckIn({ checkInId, symptomScore, videoBlob });
//   console.log("Check-in result:", result); // { score, tier }
// });
