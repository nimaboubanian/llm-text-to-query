// MongoDB Example: Blog Platform Database
// Run this in mongosh or via MongoDB init script

// Switch to the blog database
db = db.getSiblingDB('blog_platform');

// Create users collection with sample data
db.users.insertMany([
  {
    _id: ObjectId(),
    username: "tech_writer",
    email: "tech@blog.com",
    displayName: "Tech Writer",
    bio: "Passionate about technology and software development",
    followers: 1250,
    following: 45,
    createdAt: new Date("2023-01-15")
  },
  {
    _id: ObjectId(),
    username: "travel_jane",
    email: "jane@travels.com",
    displayName: "Jane Adventures",
    bio: "Exploring the world one city at a time",
    followers: 8500,
    following: 320,
    createdAt: new Date("2022-06-20")
  },
  {
    _id: ObjectId(),
    username: "foodie_chef",
    email: "chef@kitchen.com",
    displayName: "Chef Mike",
    bio: "Professional chef sharing recipes and tips",
    followers: 15000,
    following: 200,
    createdAt: new Date("2021-11-01")
  },
  {
    _id: ObjectId(),
    username: "fitness_guru",
    email: "fit@health.com",
    displayName: "Fitness Guru",
    bio: "Helping you achieve your fitness goals",
    followers: 25000,
    following: 150,
    createdAt: new Date("2020-03-10")
  }
]);

// Get user IDs for references
var techWriter = db.users.findOne({username: "tech_writer"})._id;
var travelJane = db.users.findOne({username: "travel_jane"})._id;
var foodieChef = db.users.findOne({username: "foodie_chef"})._id;
var fitnessGuru = db.users.findOne({username: "fitness_guru"})._id;

// Create posts collection with sample data
db.posts.insertMany([
  {
    title: "Getting Started with Docker",
    slug: "getting-started-docker",
    content: "Docker is a powerful containerization platform that allows you to package applications...",
    author: techWriter,
    tags: ["docker", "devops", "containers", "tutorial"],
    category: "Technology",
    views: 5420,
    likes: 234,
    status: "published",
    publishedAt: new Date("2024-01-10"),
    createdAt: new Date("2024-01-08")
  },
  {
    title: "10 Days in Japan",
    slug: "10-days-japan",
    content: "My incredible journey through Tokyo, Kyoto, and Osaka...",
    author: travelJane,
    tags: ["japan", "travel", "asia", "adventure"],
    category: "Travel",
    views: 12300,
    likes: 892,
    status: "published",
    publishedAt: new Date("2024-02-15"),
    createdAt: new Date("2024-02-10")
  },
  {
    title: "Perfect Homemade Pasta",
    slug: "homemade-pasta-recipe",
    content: "Learn how to make authentic Italian pasta from scratch...",
    author: foodieChef,
    tags: ["pasta", "italian", "recipe", "cooking"],
    category: "Food",
    views: 8900,
    likes: 567,
    status: "published",
    publishedAt: new Date("2024-03-01"),
    createdAt: new Date("2024-02-28")
  },
  {
    title: "30-Day Fitness Challenge",
    slug: "30-day-fitness-challenge",
    content: "Transform your body with this comprehensive workout plan...",
    author: fitnessGuru,
    tags: ["fitness", "workout", "health", "challenge"],
    category: "Health",
    views: 45000,
    likes: 3200,
    status: "published",
    publishedAt: new Date("2024-01-01"),
    createdAt: new Date("2023-12-28")
  },
  {
    title: "Introduction to Machine Learning",
    slug: "intro-machine-learning",
    content: "Machine learning is revolutionizing how we build software...",
    author: techWriter,
    tags: ["ml", "ai", "python", "data-science"],
    category: "Technology",
    views: 7800,
    likes: 445,
    status: "published",
    publishedAt: new Date("2024-03-20"),
    createdAt: new Date("2024-03-18")
  }
]);

// Get post IDs for comments
var dockerPost = db.posts.findOne({slug: "getting-started-docker"})._id;
var japanPost = db.posts.findOne({slug: "10-days-japan"})._id;
var pastaPost = db.posts.findOne({slug: "homemade-pasta-recipe"})._id;
var fitnessPost = db.posts.findOne({slug: "30-day-fitness-challenge"})._id;

// Create comments collection
db.comments.insertMany([
  {
    postId: dockerPost,
    author: travelJane,
    content: "Great tutorial! Finally understood Docker.",
    likes: 15,
    createdAt: new Date("2024-01-12")
  },
  {
    postId: dockerPost,
    author: fitnessGuru,
    content: "Very helpful for beginners!",
    likes: 8,
    createdAt: new Date("2024-01-15")
  },
  {
    postId: japanPost,
    author: techWriter,
    content: "Amazing photos! Adding Japan to my bucket list.",
    likes: 25,
    createdAt: new Date("2024-02-18")
  },
  {
    postId: pastaPost,
    author: travelJane,
    content: "Made this yesterday, turned out perfect!",
    likes: 42,
    createdAt: new Date("2024-03-05")
  },
  {
    postId: fitnessPost,
    author: techWriter,
    content: "Day 15 and already seeing results!",
    likes: 67,
    createdAt: new Date("2024-01-16")
  },
  {
    postId: fitnessPost,
    author: foodieChef,
    content: "Combining this with my healthy recipes!",
    likes: 33,
    createdAt: new Date("2024-01-20")
  }
]);

// Create indexes for better query performance
db.users.createIndex({ username: 1 }, { unique: true });
db.users.createIndex({ email: 1 }, { unique: true });
db.posts.createIndex({ slug: 1 }, { unique: true });
db.posts.createIndex({ author: 1 });
db.posts.createIndex({ tags: 1 });
db.posts.createIndex({ category: 1 });
db.posts.createIndex({ publishedAt: -1 });
db.comments.createIndex({ postId: 1 });
db.comments.createIndex({ author: 1 });

print("Blog platform database initialized successfully!");
