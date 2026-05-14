# TravelAgent — MVP Feature Spec v1

**Status:** Planning  
**Last Updated:** April 2026

---

## Overview

TravelAgent is a conversational travel planning assistant. You can start with something as open-ended as "where should I go in June?" or as specific as "I want to fly from Mumbai to Tokyo for 10 days" — the agent meets you where you are. It combines real flight data, weather forecasts, destination research, and cost estimates to help you make informed decisions, whether you're still figuring out where to go or already deep into planning a specific trip.

---

## Features

### 1. Understanding What You Want

The agent picks up your travel preferences through natural conversation — your travel style (backpacker, mid-range, luxury), activity interests (nature, culture, food, nightlife, adventure), climate preferences, trip duration, budget, and dates. It asks only what it genuinely needs, and only when it needs it. Your preferences are carried through the entire conversation and shape every recommendation and estimate.

---

### 2. Destination Suggestions

When you're not sure where to go, the agent suggests destinations that match your preferences — with real context for each one: what the vibe is like, whether it fits your budget, what the weather will be like during your window, typical daily costs, and what there is to do. You can ask it to compare several options, dig deeper into any of them, or shift the criteria entirely. Destination selection and destination research happen together, not in sequence.

---

### 3. Flight Search

The agent looks up real flight options for any origin–destination–date combination you're considering. It returns a few options showing the airline, total price, number of stops, and travel time. Prices are shown in both USD and your home currency. You can ask it to check flights for multiple destinations if you're still deciding, or explore different dates to find better options.

---

### 4. Weather & Timing

The agent retrieves weather conditions for any destination and time window you're considering — daily highs and lows, precipitation chances, and a plain-language summary. For dates far enough out that a precise forecast isn't available, it provides historical climate averages for that period, clearly labeled. You can ask for weather on multiple destinations at once when comparing options.

If you don't have dates in mind, the agent can help you find the right time to go. It considers weather patterns alongside other timing factors: destination festivals you might want to attend or avoid (cherry blossoms, Rio Carnival, Golden Week crowds), public holidays at the destination that affect prices and availability, and public holidays in your home country that open up long weekends. For example: "when should I visit Japan on a budget of ₹1 lakh?" gets a recommendation that accounts for weather, off-peak pricing, and whether Golden Week or other busy periods fall in that window.

---

### 5. Destination Research

The agent researches any destination you're curious about: top things to do and see, estimated daily costs for food and local transport, visa requirements for your nationality, and a brief safety summary. This comes from current web sources, not the agent's built-in knowledge, so it stays fresh and is attributed to its source. You can ask for this level of detail on one place or several.

---

### 6. Budget Breakdown

The agent gives you a cost breakdown for any trip you're considering — flights, estimated accommodation, and daily expenses — shown as a range rather than a false-precision single number, in both USD and your home currency using a live exchange rate. If you're comparing destinations, it shows the breakdown side by side. If you've mentioned a total budget, it tells you how each option sits relative to it.

---

### 7. Artifact Export

At any point you can ask the agent to save what you've worked through as a Markdown document. You decide what goes in it — a comparison of destinations, an itinerary, an activity list by interest, a cost summary, packing notes, or any combination. The agent writes it using everything gathered in the conversation and saves it as a file you can share or edit. Asking for a revised version saves a new file without overwriting the previous one.

---

## What This Version Does Not Do

- Book flights, hotels, or activities
- Handle group or multi-passenger planning
- Persist your preferences or history between separate sessions
- Provide a web or mobile interface
