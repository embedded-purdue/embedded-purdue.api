"use client";
import { useState, useEffect } from "react";

export default function PartOrderRequestPage() {
  const [projname, setProjname] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [price, setPrice] = useState("");
  const [link, setLink] = useState("");

  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");

  const [items, setItems] = useState([]);

  // Load all submitted items
  async function loadItems() {
    const res = await fetch("http://localhost:8000/items");
    const data = await res.json();
    setItems(data);
  }

  useEffect(() => {
    loadItems();
  }, []);

  // Submit new request
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStatus("");

    const requestBody = {
      projname,
      owner_id: parseInt(ownerId, 10),
      price: parseFloat(price),
      link,
    };

    try {
      const res = await fetch("http://localhost:8000/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      const data = await res.json();
      setStatus("Successfully submitted!");

      // Refresh table
      loadItems();

      // Clear fields
      setProjname("");
      setOwnerId("");
      setPrice("");
      setLink("");
    } catch (err: any) {
      setStatus("Error: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="p-6 max-w-4xl mx-auto">
      {/* ------------------ FORM CARD ------------------- */}
      <section className="grid gap-4 rounded-xl border border-border bg-card p-6 shadow-sm">
        <h2 className="text-2xl font-semibold">Part Order Request</h2>

        <form className="grid gap-3" onSubmit={handleSubmit}>
          {/* Project Name */}
          <label className="grid gap-1">
            <span className="text-sm text-muted-foreground">Project Name</span>
            <input
              className="rounded-md border border-border bg-background p-2"
              value={projname}
              onChange={(e) => setProjname(e.target.value)}
              placeholder="e.g., RC Car Upgrade"
              required
            />
          </label>

          {/* Owner ID */}
          <label className="grid gap-1">
            <span className="text-sm text-muted-foreground">Owner ID</span>
            <input
              type="number"
              className="rounded-md border border-border bg-background p-2"
              value={ownerId}
              onChange={(e) => setOwnerId(e.target.value)}
              placeholder="Enter your user ID"
              required
            />
          </label>

          {/* Price */}
          <label className="grid gap-1">
            <span className="text-sm text-muted-foreground">Price</span>
            <input
              type="number"
              step="0.01"
              min="0"
              className="rounded-md border border-border bg-background p-2"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder="e.g., 14.99"
              required
            />
          </label>

          {/* Link */}
          <label className="grid gap-1">
            <span className="text-sm text-muted-foreground">Product Link</span>
            <input
              type="url"
              className="rounded-md border border-border bg-background p-2"
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://example.com/product"
              required
            />
          </label>

          <button
            disabled={busy || !projname || !ownerId || !price || !link}
            className="rounded-md bg-primary px-4 py-2 font-semibold text-primary-foreground disabled:opacity-60"
          >
            {busy ? "Submitting…" : "Submit Request"}
          </button>

          {status && <p className="text-sm text-muted-foreground">{status}</p>}
        </form>
      </section>

      {/* ------------------ TABLE ------------------- */}
      <section className="mt-8 rounded-xl border border-border bg-card p-6 shadow-sm">
        <h3 className="text-xl font-semibold mb-4">Submitted Part Orders</h3>

        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No part requests yet.</p>
        ) : (
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-left border-b border-border">
                <th className="p-2">Item ID</th>
                <th className="p-2">Project</th>
                <th className="p-2">Owner</th>
                <th className="p-2">Price</th>
                <th className="p-2">Link</th>
              </tr>
            </thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.item_id} className="border-b border-border">
                  <td className="p-2">{i.item_id}</td>
                  <td className="p-2">{i.projname}</td>
                  <td className="p-2">{i.owner_id}</td>
                  <td className="p-2">${i.price.toFixed(2)}</td>
                  <td className="p-2">
                    <a
                      href={i.link}
                      target="_blank"
                      rel="noreferrer"
                      className="text-primary underline"
                    >
                      View
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
