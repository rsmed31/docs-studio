// Who may enter your Docs Studio hub besides the owner (the account made at /#/setup).
// Everyone else is refused at sign-in, even with an account. The owner can also authorize people from the
// home page (People with access), and HUB_ALLOWED_EMAILS (comma-separated, Netlify environment) adds more.
export default {
  name: "Docs Studio",
  allowed: [
    // "teammate@example.com",
  ],
};
