"use strict";

(() => {
  let accessToken = "";
  const output = document.getElementById("output");
  const value = (id) => document.getElementById(id).value.trim();

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    if (options.body) headers.set("Content-Type", "application/json");
    const response = await fetch(path, { ...options, headers });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
    output.textContent = JSON.stringify(body, null, 2);
    return body;
  }

  async function run(action) {
    try {
      await action();
    } catch (error) {
      output.textContent = error.message;
    }
  }

  document.getElementById("login").addEventListener("click", () => run(async () => {
    const result = await request("/api/v3/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: value("username"), password: value("password") }),
    });
    accessToken = result.access_token;
    document.getElementById("password").value = "";
    output.textContent = "Signed in. Bearer token is held in memory only.";
  }));
  document.getElementById("profile").addEventListener("click", () =>
    run(() => request("/api/v3/users/me")));
  document.getElementById("search").addEventListener("click", () => run(() => {
    const params = new URLSearchParams();
    if (value("origin")) params.set("origin", value("origin"));
    if (value("destination")) params.set("destination", value("destination"));
    return request(`/api/v3/search/flights?${params.toString()}`);
  }));

  function bookingPayload() {
    return {
      flight_id: value("flight-id"),
      quantity: Number(value("quantity")),
      traveler_name: value("traveler-name"),
      passport_number: value("passport-number"),
    };
  }

  document.getElementById("hold").addEventListener("click", () => run(() =>
    request("/api/v3/holds", {
      method: "POST",
      body: JSON.stringify({
        flight_id: value("flight-id"),
        quantity: Number(value("quantity")),
      }),
    })));
  document.getElementById("book").addEventListener("click", () => run(async () => {
    const booking = await request("/api/v3/bookings", {
      method: "POST",
      body: JSON.stringify(bookingPayload()),
    });
    document.getElementById("booking-id").value = booking.id;
  }));
  document.getElementById("booking").addEventListener("click", () => run(() =>
    request(`/api/v3/bookings/${encodeURIComponent(value("booking-id"))}`)));
  document.getElementById("pay").addEventListener("click", () => run(() =>
    request(`/api/v3/bookings/${encodeURIComponent(value("booking-id"))}/pay`, {
      method: "POST",
    })));
  document.getElementById("cancel").addEventListener("click", () => run(() =>
    request(`/api/v3/bookings/${encodeURIComponent(value("booking-id"))}/cancel`, {
      method: "POST",
    })));
})();
