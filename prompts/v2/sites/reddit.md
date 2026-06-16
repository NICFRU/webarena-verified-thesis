# Discussion Forum Executor Context

- The benchmark forum is Postmill-like, not public Reddit.
- Forum pages usually use `/f/<ForumName>`, not `/r/<ForumName>`.
- Newest-post listings often use `/f/<ForumName>/new`.
- The all-posts listing is usually `/all`.
- For most-recent tasks, prefer a visible New link or a `/new` route.
- For RETRIEVE tasks, navigate to the relevant listing or post and return only
  the requested fields.
- For vote/post/comment MUTATE tasks, click or submit the actual visible control;
  a final success message without the mutation action is invalid.
- For bulk vote/like MUTATE tasks, such as liking all submissions by an author
  in a forum, identify the matching target submissions first, then click each
  target's upvote/like control exactly once. Do not click an already-upvoted
  control again, because voting controls can toggle back to neutral/downvote.
- For subscribe MUTATE tasks that say "from the page of" a top/controversial/
  most-commented post, first open that exact post page in the requested sorted
  context, then click the forum Subscribe control. A generic forum page or post
  page without the Subscribe action is not completion.
- For reply/comment MUTATE tasks, open the exact target post and use the Reply
  control attached to the requested comment, user, or reply target. Do not use a
  generic post-level comment form when the task names a specific comment/reply
  context.
- For image re-post MUTATE tasks, get the source image URL from visible links,
  image href/src text, current URL, or candidate context. Do not use unsupported
  helper actions such as `get_url()`, `copy_url()`, or `get_attribute(...)`.
  Submit a new post with the exact requested title, target forum, and image URL.
