# User Manual - Complaint Router

This guide is for customer-care agents and team leads. No technical knowledge is needed.

## 1. What the Complaint Router does

You paste a customer's complaint. In about one second the Complaint Router tells you:

* **which team** should handle it (for example *Mortgage Servicing Team*),
* **how sure** it is (confidence),
* whether the complaint is **URGENT** and why,
* **which words** led to the decision,
* **similar complaints** from the past and how they were resolved.

It is an assistant. You always have the final say.

## 2. Opening the application

Open a web browser (Chrome, Firefox or Edge) and go to the address your administrator gave you, usually **http://localhost:8080**.

At the top right you will see a status light:

| Light | Meaning |
|---|---|
| 🟢 *Model v2 online* | Everything works. |
| 🔴 *Model offline* | The system is starting or being updated. A red message explains this and the **Route complaint** button is paused. Wait a minute. |
| 🔴 *Server unreachable* | The application is not running. Contact your administrator. |

## 3. Routing a complaint, step by step

1. Click the **Route a complaint** tab (it opens by default).
2. **Paste** the complaint text into the large box. Write at least 20 characters; the message under the box tells you how many more are needed.
   *Tip:* to see how it works, click one of the **example** buttons under the box.
3. Click **Route complaint** (or press **Ctrl + Enter**).
4. Read the result card on the right (on a phone, it appears below the box).

## 4. Understanding the result

The top of the result has three boxes:

**Routed to** - the team that should receive the complaint, with its category.

**Priority**
* 🔴 **Urgent** - handle this complaint first. Typical reasons: fraud, a home or car about to be taken away, wage garnishment, threats from a collector, or a customer who cannot pay.
* 🟢 **Normal** - handle in the usual order.

**Confidence** - how sure the system is, from 0 % to 100 %, also shown in words:
* **High** (80 % or more) or **Medium** (50-79 %): you can usually follow the suggestion.
* **Low** (below 50 %): shown in yellow with *needs review*. Read the complaint yourself and choose the team (see step 5).

**Next step** - the coloured box under them tells you what to do in one sentence:
* 🔴 **Handle first** - urgent; send it to the team today and escalate it to a team lead.
* 🟡 **Check before assigning** - the system is unsure; check the team yourself.
* 🟢 **Ready to assign** - send it to the team in the normal queue.

**Copy summary** (bottom right) copies the team, priority, confidence and next step so you can paste them into your ticket system.

If you change the complaint text after routing, the result fades and says *"The text was changed"*. Click **Route complaint** again to get an up-to-date result.

**Why this priority** - the reasons in plain words. "*Severe situation, always escalated: foreclosure*" means the complaint mentions a situation the bank must always treat as urgent.

**Words that drove the decision** - the words that most influenced the team choice. If they look unrelated to the complaint, double-check the result.

**Other possible categories** - the second and third choices with their likelihood. These are useful when confidence is low.

**Similar past complaints** - earlier cases that read alike, with their category and the outcome (e.g. *Closed with monetary relief*). Use them as a reference for how similar cases were handled.

## 5. Telling the system whether it was right

At the bottom of the result:

* Click **✓ Yes, correct** if the result was right.
* Otherwise choose the correct team in the list, tick **Urgent** if needed, and click **Send correction**.

A green "*Thank you…*" message replaces the buttons, so feedback cannot be sent twice by mistake. Your corrections are stored **encrypted** and teach the system over time.

## 6. Common messages

| Message | What to do |
|---|---|
| "Please write a bit more (N more characters)." | Add more detail about the problem. |
| "The text was changed. Click Route complaint again…" | You edited the complaint after routing. Route it again. |
| "The text should describe the problem in words." | The box contains mostly numbers or symbols. Paste the actual complaint text. |
| "The routing model is not available right now…" | Wait a minute and try again. If it persists, tell your administrator. |
| "The server took too long to answer." | Try again; the system may be busy retraining. |

## 7. Other tabs (for team leads and administrators)

* **Pipeline console** - the "factory" that builds the model: each step, when it last ran, whether it succeeded and how fast it was. It also lists model versions (the one marked **@champion** is live) and retraining runs. **Retrain now…** asks for the admin token.
* **Monitoring** - live charts: number of complaints, response speed, mix of categories, share of urgent complaints and **data drift** (whether today's complaints look different from what the model learned). When drift persists, the system retrains itself automatically.
* **Help** - this same manual, inside the application.

## 8. Privacy

* Complaint text is never written to the system logs.
* Corrections are encrypted before they are saved.
* Do not paste passwords or full card numbers. The system masks long numbers, e-mails and phone numbers, but it is better not to include them.
